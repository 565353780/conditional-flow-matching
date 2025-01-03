import sys
sys.path.append("../ma-sh/")
sys.path.append("../ulip-manage/")
sys.path.append('../distribution-manage/')

import os
import random
import numpy as np
import open3d as o3d
from tqdm import tqdm
from typing import Union
from math import sqrt, ceil
from shutil import copyfile

from ma_sh.Data.mesh import Mesh
from ulip_manage.Module.detector import Detector

from mash_diffusion.Config.shapenet import CATEGORY_IDS
from mash_diffusion.Method.time import getCurrentTime
from mash_diffusion.Module.cfm_sampler import CFMSampler


def toRandomIdList(dataset_folder_path: str, valid_category_id_list: Union[list, None]=None, sample_id_num: int=100) -> list:
    random_id_list = []

    if valid_category_id_list is None:
        valid_category_id_list = os.listdir(dataset_folder_path)

    for category_id in valid_category_id_list:
        category_folder_path = dataset_folder_path + category_id + '/'
        if not os.path.exists(category_folder_path):
            continue

        model_id_list = os.listdir(category_folder_path)

        if sample_id_num >= len(model_id_list):
            random_model_id_list = model_id_list
        else:
            random_model_id_list = random.sample(model_id_list, sample_id_num)

        for random_model_id in random_model_id_list:
            random_id_list.append(category_id + '/' + random_model_id.replace('.npy', ''))

    return random_id_list

def demoCondition(
    sampler: Sampler,
    detector: Detector,
    time_stamp: str,
    condition_value: Union[int, str, np.ndarray] = 18,
    sample_num: int = 9,
    timestamp_num: int = 10,
    save_folder_path: Union[str, None] = None,
    condition_type: str = 'category',
    condition_name: str = '0',
    save_results_only: bool = True,
    mash_file_path_list: Union[list, None]=None,
) -> bool:
    assert condition_type in ['category', 'image', 'points', 'text']

    if condition_type == 'category':
        assert isinstance(condition_value, int)

        condition = condition_value
    elif condition_type == 'image':
        assert isinstance(condition_value, str)

        image_file_path = condition_value
        if not os.path.exists(image_file_path):
            print('[ERROR][sampler::demoCondition]')
            print('\t condition image file not exist!')
            return False

        condition = (
            detector.encodeImageFile(image_file_path).cpu().numpy()
        )
    elif condition_type == 'points':
        assert isinstance(condition_value, np.ndarray)

        points = condition_value
        condition = (
            detector.encodePointCloud(points).cpu().numpy()
        )
    elif condition_type == 'text':
        assert isinstance(condition_value, str)

        text = condition_value
        condition = (
            detector.encodeText(condition_value).cpu().numpy()
        )
    else:
        print('[ERROR][sampler::demoCondition]')
        print('\t condition type not valid!')
        return False

    condition_info = condition_type + '/' + condition_name

    print("start diffuse", sample_num, "mashs....")
    if mash_file_path_list is None:
        sampled_array = sampler.sample(sample_num, condition, timestamp_num)
    else:
        sampled_array = sampler.sampleWithFixedAnchors(mash_file_path_list, sample_num, condition, timestamp_num)

    object_dist = [0, 0, 0]

    row_num = ceil(sqrt(sample_num))

    mash_model = sampler.toInitialMashModel()

    for j in range(sampled_array.shape[0]):
        if save_results_only:
            if j != sampled_array.shape[0] - 1:
                continue

        if save_folder_path is None:
            save_folder_path = './output/sample/' + time_stamp + '/'
        current_save_folder_path = save_folder_path + 'iter_' + str(j) + '/' + condition_info + '/'

        os.makedirs(current_save_folder_path, exist_ok=True)

        if condition_type == 'image':
            copyfile(image_file_path, current_save_folder_path + 'condition_image.png')
        elif condition_type == 'points':
            pcd = o3d.geometry.PointCloud()
            pcd.points = o3d.utility.Vector3dVector(points)
            o3d.io.write_point_cloud(current_save_folder_path + 'condition_pcd.ply', pcd)
        elif condition_type == 'text':
            with open(current_save_folder_path + 'condition_text.txt', 'w') as f:
                f.write(text)

        print("start create mash files,", j + 1, '/', sampled_array.shape[0], "...")
        for i in tqdm(range(sample_num)):

            mash_params = sampled_array[j][i]

            sh2d = 2 * sampler.mask_degree + 1
            ortho_poses = mash_params[:, :6]
            positions = mash_params[:, 6:9]
            mask_params = mash_params[:, 9 : 9 + sh2d]
            sh_params = mash_params[:, 9 + sh2d :]

            mash_model.loadParams(
                mask_params=mask_params,
                sh_params=sh_params,
                positions=positions,
                ortho6d_poses=ortho_poses
            )

            translate = [
                int(i / row_num) * object_dist[0],
                (i % row_num) * object_dist[1],
                j * object_dist[2],
            ]

            mash_model.translate(translate)

            mash_model.saveParamsFile(current_save_folder_path + 'mash/sample_' + str(i+1) + '_mash.npy', True)
            mash_model.saveAsPcdFile(current_save_folder_path + 'pcd/sample_' + str(i+1) + '_pcd.ply', True)

    return True

def demo(save_folder_path: Union[str, None] = None):
    cfm_model_file_path = "../../output/24depth_512cond_2000epoch/total_model_last.pth".replace('../../', './')
    use_ema = True
    sample_id_num = 1
    sample_num = 10
    timestamp_num = 2
    device = 'cuda:0'
    save_results_only = True
    sample_category = False
    sample_image = False
    sample_points = False
    sample_text = False
    sample_fixed_anchor = True

    ulip_model_file_path = '/home/chli/chLi/Model/ULIP2/pretrained_models_ckpt_zero-sho_classification_pointbert_ULIP-2.pt'
    open_clip_model_file_path = '/home/chli/Model/CLIP-ViT-bigG-14-laion2B-39B-b160k/open_clip_pytorch_model.bin'

    sampler = Sampler(cfm_model_file_path, use_ema, device)
    # detector = Detector(ulip_model_file_path, open_clip_model_file_path, device)
    detector = None

    time_stamp = getCurrentTime()

    # 0: airplane
    # 2: bag
    # 6: bench
    # 9: bottle
    # 16: car
    # 18: chair
    # 22: monitor
    # 23: earphone
    # 24: spigot
    # 26: guitar
    # 27: helmet
    # 30: lamp
    # 33: mailbox
    # 40: gun
    # 44: long-gun
    # 46: skateboard
    # 47: sofa
    # 49: table
    # 52: train
    # 53: watercraft
    valid_category_id_list = [
        '02691156', # 0: airplane
        '02773838', # 2: bag
        '02828884', # 6: bench
        '02876657', # 9: bottle
        '02958343', # 16: bottle
        '03001627', # 18: chair
        '03211117', # 22: monitor
        '03261776', # 23: earphone
        '03325088', # 24: spigot
        '03467517', # 26: guitar
        '03513137', # 27: helmet
        '03636649', # 30: lamp
        '03710193', # 33: mailbox
        '03948459', # 40: gun
        '04090263', # 44: long-gun
        '04225987', # 46: skateboard
        '04256520', # 47: sofa
        '04379243', # 49: table
        '04468005', # 52: train
        '04530566', # 53: watercraft
    ]
    valid_category_id_list = [
        '03001627', # 18: chair
    ]

    if sample_category:
        for categoty_id in valid_category_id_list:
            print('start sample for category ' + categoty_id + '...')
            category_idx = CATEGORY_IDS[categoty_id]
            demoCondition(sampler, detector, time_stamp, category_idx, sample_num, timestamp_num, save_folder_path, 'category', str(categoty_id), save_results_only)

    if sample_image:
        image_id_list = [
            '03001627/1a74a83fa6d24b3cacd67ce2c72c02e',
            '03001627/1a38407b3036795d19fb4103277a6b93',
            '03001627/1ab8a3b55c14a7b27eaeab1f0c9120b7',
            '02691156/1a6ad7a24bb89733f412783097373bdc',
            '02691156/1a32f10b20170883663e90eaf6b4ca52',
            '02691156/1abe9524d3d38a54f49a51dc77a0dd59',
            '02691156/1adb40469ec3636c3d64e724106730cf',
        ]
        image_id_list = toRandomIdList('/home/chli/Dataset/MashV4/ShapeNet/', valid_category_id_list, sample_id_num)
        for image_id in image_id_list:
            print('start sample for image ' + image_id + '...')
            image_file_path = '/home/chli/chLi/Dataset/CapturedImage/ShapeNet/' + image_id + '/y_5_x_3.png'
            if not os.path.exists(image_file_path):
                continue
            demoCondition(sampler, detector, time_stamp, image_file_path, sample_num, timestamp_num, save_folder_path, 'image', image_id, save_results_only)

    if sample_points:
        points_id_list = [
            '03001627/1a74a83fa6d24b3cacd67ce2c72c02e',
            '03001627/1a38407b3036795d19fb4103277a6b93',
            '03001627/1ab8a3b55c14a7b27eaeab1f0c9120b7',
            '02691156/1a6ad7a24bb89733f412783097373bdc',
            '02691156/1a32f10b20170883663e90eaf6b4ca52',
            '02691156/1abe9524d3d38a54f49a51dc77a0dd59',
            '02691156/1adb40469ec3636c3d64e724106730cf',
        ]
        points_id_list = toRandomIdList('/home/chli/Dataset/MashV4/ShapeNet/', valid_category_id_list, sample_id_num)
        for points_id in points_id_list:
            print('start sample for points ' + points_id + '...')
            mesh_file_path = '/home/chli/chLi/Dataset/ManifoldMesh/ShapeNet/' + points_id + '.obj'
            if not os.path.exists(mesh_file_path):
                continue
            points = Mesh(mesh_file_path).toSamplePoints(8192)
            demoCondition(sampler, detector, time_stamp, points, sample_num, timestamp_num, save_folder_path, 'points', points_id, save_results_only)

    if sample_text:
        text_list = [
            'a tall chair',
            'a short chair',
            'a circle chair',
            'horizontal slats on top of back',
            'one big hole between back and seat',
            'this chair has wheels',
            'vertical back ribs',
        ]
        for i, text in enumerate(text_list):
            print('start sample for text [' + text + ']...')
            demoCondition(sampler, detector, time_stamp, text, sample_num, timestamp_num, save_folder_path, 'text', str(i), save_results_only)

    if sample_fixed_anchor:
        mash_file_path_list = [
            '../ma-sh/output/combined_mash.npy',
        ]
        categoty_id = '03001627'
        print('start sample for fixed anchor category ' + categoty_id + '...')
        category_idx = CATEGORY_IDS[categoty_id]
        demoCondition(
            sampler,
            detector,
            time_stamp,
            category_idx,
            sample_num,
            timestamp_num,
            save_folder_path,
            'category',
            'fixed_anchor',
            save_results_only,
            mash_file_path_list,
        )

    return True
