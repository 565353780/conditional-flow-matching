import os
import torch
import numpy as np
from torch import nn
from tqdm import tqdm
from typing import Union
from torchdyn.core import NeuralODE
from torch.utils.data import DataLoader
from torch.optim import Optimizer, AdamW
from torch.optim.lr_scheduler import (
    LRScheduler,
    CosineAnnealingWarmRestarts,
    ReduceLROnPlateau,
)

from torchcfm.conditional_flow_matching import *

from conditional_flow_matching.Dataset.mash import MashDataset
from conditional_flow_matching.Dataset.image_embedding import ImageEmbeddingDataset
from conditional_flow_matching.Model.unet2d import MashUNet
from conditional_flow_matching.Model.mash_net import MashNet
from conditional_flow_matching.Method.time import getCurrentTime
from conditional_flow_matching.Method.path import createFileFolder, removeFile, renameFile
from conditional_flow_matching.Module.logger import Logger


class Trainer(object):
    def __init__(
        self,
        dataset_root_folder_path: str,
        batch_size: int = 400,
        accum_iter: int = 1,
        num_workers: int = 4,
        model_file_path: Union[str, None] = None,
        dtype=torch.float32,
        device: str = "cpu",
        warm_epoch_step_num: int = 20,
        warm_epoch_num: int = 10,
        finetune_step_num: int = 400,
        lr: float = 1e-2,
        weight_decay: float = 1e-4,
        factor: float = 0.9,
        patience: int = 1,
        min_lr: float = 1e-4,
        save_result_folder_path: Union[str, None] = None,
        save_log_folder_path: Union[str, None] = None,
    ) -> None:
        self.accum_iter = accum_iter
        self.dtype = dtype
        self.device = device

        self.warm_epoch_step_num = warm_epoch_step_num
        self.warm_epoch_num = warm_epoch_num

        self.finetune_step_num = finetune_step_num

        self.step = 0
        self.loss_min = float("inf")

        self.best_params_dict = {}

        self.lr = lr
        self.weight_decay = weight_decay
        self.factor = factor
        self.patience = patience
        self.min_lr = min_lr

        self.save_result_folder_path = save_result_folder_path
        self.save_log_folder_path = save_log_folder_path
        self.save_file_idx = 0
        self.logger = Logger()

        mash_dataset = MashDataset(dataset_root_folder_path, 'train')
        image_embedding_dataset = ImageEmbeddingDataset(dataset_root_folder_path, 'train')

        mash_dataloader = DataLoader(
            mash_dataset,
            shuffle=True,
            batch_size=batch_size,
            num_workers=num_workers,
        )

        image_embedding_dataloader = DataLoader(
            image_embedding_dataset,
            shuffle=True,
            batch_size=batch_size,
            num_workers=num_workers,
        )

        self.dataloader_dict = {
            'mash': mash_dataloader,
            'image_embedding': image_embedding_dataloader,
        }

        model_id = 2
        if model_id == 1:
            self.model = MashUNet(768).to(device)
        elif model_id == 2:
            self.model = MashNet().to(device)

        self.FM = ExactOptimalTransportConditionalFlowMatcher(sigma=0.0)
        self.node = NeuralODE(self.model, solver="dopri5", sensitivity="adjoint", atol=1e-4, rtol=1e-4)

        self.loss_fn = nn.MSELoss()

        self.initRecords()

        if model_file_path is not None:
            self.loadModel(model_file_path)

        self.min_lr_reach_time = 0
        return

    def initRecords(self) -> bool:
        self.save_file_idx = 0

        current_time = getCurrentTime()

        if self.save_result_folder_path == "auto":
            self.save_result_folder_path = "./output/" + current_time + "/"
        if self.save_log_folder_path == "auto":
            self.save_log_folder_path = "./logs/" + current_time + "/"

        if self.save_result_folder_path is not None:
            os.makedirs(self.save_result_folder_path, exist_ok=True)
        if self.save_log_folder_path is not None:
            os.makedirs(self.save_log_folder_path, exist_ok=True)
            self.logger.setLogFolder(self.save_log_folder_path)
        return True

    def loadModel(self, model_file_path: str) -> bool:
        if not os.path.exists(model_file_path):
            print("[ERROR][Trainer::loadModel]")
            print("\t model file not exist!")
            print("\t model_file_path:", model_file_path)
            return False

        model_state_dict = torch.load(model_file_path)
        self.model.load_state_dict(model_state_dict["model"])
        return True

    def getLr(self, optimizer) -> float:
        return optimizer.state_dict()["param_groups"][0]["lr"]

    def toTrainStepNum(self, scheduler: LRScheduler) -> int:
        if not isinstance(scheduler, CosineAnnealingWarmRestarts):
            return self.finetune_step_num

        if scheduler.T_mult == 1:
            warm_epoch_num = scheduler.T_0 * self.warm_epoch_num
        else:
            warm_epoch_num = int(
                scheduler.T_mult
                * (1.0 - pow(scheduler.T_mult, self.warm_epoch_num))
                / (1.0 - scheduler.T_mult)
            )

        return self.warm_epoch_step_num * warm_epoch_num

    def trainStep(
        self,
        data: dict,
        optimizer: Optimizer,
    ) -> dict:
        cfm_mash_params = data['cfm_mash_params'].to(self.device)
        condition = data['condition'].to(self.device)

        cfm_mash_params_noise = torch.randn_like(cfm_mash_params)

        t, xt, ut, _, y1 = self.FM.guided_sample_location_and_conditional_flow(cfm_mash_params_noise, cfm_mash_params, y1=condition)

        vt = self.model(xt, y1, t)

        loss = self.loss_fn(vt, ut)

        accum_loss = loss / self.accum_iter
        accum_loss.backward()

        if (self.step + 1) % self.accum_iter == 0:
            optimizer.step()
            optimizer.zero_grad()

        loss_dict = {
            "Loss": loss.item(),
        }

        return loss_dict

    def checkStop(
        self, optimizer: Optimizer, scheduler: LRScheduler, loss_dict: dict
    ) -> bool:
        if not isinstance(scheduler, CosineAnnealingWarmRestarts):
            scheduler.step(loss_dict["Loss"])

            if self.getLr(optimizer) == self.min_lr:
                self.min_lr_reach_time += 1

            return self.min_lr_reach_time > self.patience

        current_warm_epoch = self.step / self.warm_epoch_step_num
        scheduler.step(current_warm_epoch)

        return current_warm_epoch >= self.warm_epoch_num

    def toCondition(self, data: dict) -> Union[torch.Tensor, None]:
        if 'category_id' in data.keys():
            return data['category_id']

        if 'image_embedding' in data.keys():
            image_embedding = data["image_embedding"]
            key_idx = np.random.choice(len(image_embedding.keys()))
            key = list(image_embedding.keys())[key_idx]
            condition = image_embedding[key]

            return condition

        print('[ERROR][Trainer::toCondition]')
        print('\t valid condition type not found!')
        return None

    def train(
        self,
        optimizer: Optimizer,
        scheduler: LRScheduler,
    ) -> bool:
        train_step_num = self.toTrainStepNum(scheduler)
        final_step = self.step + train_step_num

        need_stop = False

        print("[INFO][Trainer::train]")
        print("\t start training ...")

        loss_dict_list = []
        while self.step < final_step:
            self.model.train()

            for data_name, dataloader in self.dataloader_dict.items():
                print('[INFO][Trainer::train]')
                print('\t start training on dataset [', data_name, ']...')

                pbar = tqdm(total=len(dataloader))

                for data in dataloader:
                    condition = self.toCondition(data)
                    if condition is None:
                        print('[ERROR][Trainer::train]')
                        print('\t toCondition failed!')
                        continue

                    conditional_data = {
                        'cfm_mash_params': data['cfm_mash_params'],
                        'condition': condition,
                    }

                    train_loss_dict = self.trainStep(conditional_data, optimizer)

                    loss_dict_list.append(train_loss_dict)

                    lr = self.getLr(optimizer)

                    if (self.step + 1) % self.accum_iter == 0:
                        for key in train_loss_dict.keys():
                            value = 0
                            for i in range(len(loss_dict_list)):
                                value += loss_dict_list[i][key]
                            value /= len(loss_dict_list)
                            self.logger.addScalar("Train/" + key, value, self.step)
                        self.logger.addScalar("Train/Lr", lr, self.step)

                        loss_dict_list = []

                    pbar.set_description(
                        "LOSS %.6f LR %.4f"
                        % (
                            train_loss_dict["Loss"],
                            self.getLr(optimizer) / self.lr,
                        )
                    )

                    self.step += 1
                    pbar.update(1)

                    if self.checkStop(optimizer, scheduler, train_loss_dict):
                        need_stop = True
                        break

                    if self.step >= final_step:
                        need_stop = True
                        break

                pbar.close()

                self.autoSaveModel(train_loss_dict['Loss'], data_name)

                if need_stop:
                    break

            if need_stop:
                break

        return True

    def autoTrain(
        self,
    ) -> bool:
        print("[INFO][Trainer::autoTrain]")
        print("\t start auto train mash occ decoder...")

        optimizer = AdamW(
            self.model.parameters(),
            lr=self.lr,
            weight_decay=self.weight_decay,
        )
        warm_scheduler = CosineAnnealingWarmRestarts(optimizer, T_0=1, T_mult=1)
        finetune_scheduler = ReduceLROnPlateau(
            optimizer,
            mode="min",
            factor=self.factor,
            patience=self.patience,
            min_lr=self.min_lr,
        )

        self.train(optimizer, warm_scheduler)
        for param_group in optimizer.param_groups:
            param_group["lr"] = self.lr
        self.train(optimizer, finetune_scheduler)

        return True

    def saveModel(self, save_model_file_path: str) -> bool:
        createFileFolder(save_model_file_path)

        model_state_dict = {
            "model": self.model.state_dict(),
            "loss_min": self.loss_min,
        }

        torch.save(model_state_dict, save_model_file_path)

        return True

    def autoSaveModel(self, value: float, name: str, check_lower: bool = True) -> bool:
        if self.save_result_folder_path is None:
            return False

        save_last_model_file_path = self.save_result_folder_path + name + "_model_last.pth"

        tmp_save_last_model_file_path = save_last_model_file_path[:-4] + "_tmp.pth"

        self.saveModel(tmp_save_last_model_file_path)

        removeFile(save_last_model_file_path)
        renameFile(tmp_save_last_model_file_path, save_last_model_file_path)

        #FIXME: ignore best loss since diffusion loss is kind of randomly
        return True

        if self.loss_min == float("inf"):
            if not check_lower:
                self.loss_min = -float("inf")

        if check_lower:
            if value > self.loss_min:
                return False
        else:
            if value < self.loss_min:
                return False

        self.loss_min = value

        save_best_model_file_path = self.save_result_folder_path + name + "_model_best.pth"

        tmp_save_best_model_file_path = save_best_model_file_path[:-4] + "_tmp.pth"

        self.saveModel(tmp_save_best_model_file_path)

        removeFile(save_best_model_file_path)
        renameFile(tmp_save_best_model_file_path, save_best_model_file_path)

        return True
