import sys
sys.path.append('../ma-sh/')

import os

from conditional_flow_matching.Module.fm_trainer import FMTrainer


def demo():
    dataset_root_folder_path = os.environ['HOME'] + "/Dataset/"
    batch_size = 52
    accum_iter = 5
    num_workers = 16
    # model_file_path = "./output/24depth_512cond_1300epoch/total_model_last.pth"
    model_file_path = None
    device = "auto"
    warm_step_num = 2000
    finetune_step_num = -1
    lr = 2e-5
    ema_start_step = 0
    ema_decay = 0.9999
    save_result_folder_path = "auto"
    save_log_folder_path = "auto"

    fm_trainer = FMTrainer(
        dataset_root_folder_path,
        batch_size,
        accum_iter,
        num_workers,
        model_file_path,
        device,
        warm_step_num,
        finetune_step_num,
        lr,
        ema_start_step,
        ema_decay,
        save_result_folder_path,
        save_log_folder_path,
    )

    fm_trainer.train()
    return True