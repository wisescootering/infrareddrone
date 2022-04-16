from pathlib import Path
import shutil


def odm_mapping(dirMission, multispectral_modality="VIR", copy_list=None):
    mapping_folder = "mapping_{}".format(multispectral_modality)
    path_database = Path(dirMission) / mapping_folder
    odm_camera_conf = Path(__file__).parent/ ".."/ "odm_data" / "dji_fc3170.json"
    camera_conf_dir = path_database/"camera"
    camera_conf_dir.mkdir(exist_ok=True, parents=True)
    shutil.copyfile(odm_camera_conf, camera_conf_dir/"camera_IRdrone.json")
    image_database = path_database / "images"
    image_database.mkdir(exist_ok=True, parents=True)
    cmd = "docker run -ti --rm -v {}:/datasets opendronemap/odm".format(dirMission)
    cmd+= " --project-path /datasets {}".format(mapping_folder)
    cmd+= " --cameras /datasets/{}/camera/camera_IRdrone.json".format(mapping_folder)
    cmd+= " --orthophoto-resolution 1. --ignore-gsd --fast-orthophoto --force-gps"
    with open(path_database/"odm_mapping.bat", "w") as fi:
        fi.write(cmd)
    for img in copy_list:
        shutil.copy(img, image_database)
    return image_database