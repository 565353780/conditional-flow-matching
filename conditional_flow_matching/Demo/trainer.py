import sys
sys.path.append('../ma-sh/')

import os

from conditional_flow_matching.Module.trainer import Trainer


def demo():
    dataset_root_folder_path = os.environ['HOME'] + "/Dataset/"
    batch_size = 10
    accum_iter = 1
    num_workers = 16
    # model_file_path = "./output/24depth_512cond_1300epoch/total_model_last.pth"
    model_file_path = None
    device = "auto"
    warm_step_num = 5000
    finetune_step_num = -1
    lr = 1e-5
    ema_start_step = 2000
    ema_decay = 0.9999
    save_result_folder_path = "auto"
    save_log_folder_path = "auto"

    trainer = Trainer(
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

    trainer.train()
    return True
