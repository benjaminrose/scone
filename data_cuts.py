import os
import argparse
import yaml
import pandas as pd
import numpy as np
import h5py
import json
from astropy.table import Table

parser = argparse.ArgumentParser(description='create heatmaps from lightcurve data')
parser.add_argument('--config_path', type=str, help='absolute or relative path to your yml config file, i.e. "/user/files/create_heatmaps_config.yml"')

args = parser.parse_args()
# LOAD CONFIG
with open(args.config_path, "r") as cfgfile:
    config = yaml.load(cfgfile)
METADATA_PATHS = config["metadata_paths"]
LCDATA_PATHS = config["lcdata_paths"]
OUTPUT_PATH = config["output_path"]
SN_TYPE_ID_MAP = config["sn_type_id_to_name"]
IA_FRACTION = config["Ia_fraction"]
CATEGORICAL_MIN_PER_TYPE = config["categorical_min_per_type"]
CATEGORICAL_MAX_PER_TYPE = config["categorical_max_per_type"]

if not os.path.exists(OUTPUT_PATH):
    os.makedirs(OUTPUT_PATH, exist_ok=True)

SAVE_TO_JSON = config["save_to_json"]
FROM_JSON = config["from_json"]

def apply_cuts(metadata, lcdata, thresholds):
    sn_ids = metadata[(metadata.true_target.isin(SN_TYPE_ID_MAP.keys()))]['object_id']
    metadata = metadata[metadata['object_id'].isin(sn_ids)]
    if thresholds != None:
        first_detection_threshold, num_detections_threshold, snr_threshold, active_time_threshold = thresholds
    total_by_type = {}
    passed_cuts_by_type = {}
    passed_cuts = []
    not_passed_cuts = []
    no_detections = []

    for sn_id in sn_ids:
        sn_id = int(sn_id)
        sn_metadata = metadata[metadata.object_id == sn_id]
        sn_name = SN_TYPE_ID_MAP[sn_metadata.true_target.iloc[0]]
        total_by_type[sn_name] = 1 if sn_name not in total_by_type else total_by_type[sn_name] + 1

        peak_mjd = metadata['true_peakmjd'][metadata['object_id'] == sn_id].iloc[0]
        if 'detected_bool' in lcdata.columns:
            sn_data = lcdata.loc['object_id', sn_id]['mjd', 'flux', 'flux_err', 'passband', 'detected_bool']
            # evaluate lightcurve quality -- time between detections / non-detections
            detections = np.sort(np.array(sn_data[sn_data['detected_bool'] == 1]['mjd']))
            non_detections = np.sort(np.array(sn_data[sn_data['detected_bool'] == 0]['mjd']))
            if len(detections) == 0:
                no_detections.append(sn_id)
                continue
            first_detection = detections[0]
            last_detection = detections[-1]
            non_detections_before = [x for x in non_detections if x < first_detection]
            non_detections_after = [x for x in non_detections if x > last_detection]
            
            time_to_first_detection = (first_detection - non_detections_before[-1]) if len(non_detections_before) > 0 else 100
            time_after_last_detection = (non_detections_after[0] - last_detection) if len(non_detections_after) > 0 else 100

            # evaluate lightcurve quality -- number of detections
            num_detections = len(detections)
            
            # evaluate lightcurve quality -- time span of detections
            active_time = last_detection - first_detection

            small_gap_before_detection = (time_to_first_detection <= first_detection_threshold)
            enough_detections = (num_detections >= num_detections_threshold)
            long_active_time = active_time >= active_time_threshold
            if not small_gap_before_detection or not enough_detections or not long_active_time:
                continue
        else:
            sn_data = lcdata.loc['object_id', sn_id]['mjd', 'flux', 'flux_err', 'passband']

        if thresholds == None:
            passed_cuts.append(np.string_("{}_{}".format(sn_name, sn_id)))
            continue
 
        # evaluate lightcurve quality -- cumulative s/n
        snrs = np.array(sn_data['flux'])**2 / np.array(sn_data['flux_err'])**2
        snrs = snrs[~np.isnan(snrs)] # sometimes flux err is 0
        if np.sum(snrs) < 0 or not np.isfinite(np.sum(snrs)):
            print(snrs)
        cumulative_snr = np.sqrt(np.sum(snrs))

        # define criteria
        high_snr = (cumulative_snr > snr_threshold)

        if high_snr:
            passed_cuts_by_type[sn_name] = 1 if sn_name not in passed_cuts_by_type else passed_cuts_by_type[sn_name] + 1
            passed_cuts.append(np.string_("{}_{}".format(sn_name, sn_id)))
        else:
            not_passed_cuts.append(np.string_("{}_{}".format(sn_name, sn_id)))
    print("total: {}, passed: {}".format(total_by_type, passed_cuts_by_type))
    print("sn ids with no detections: {}".format(no_detections))
    return np.array(passed_cuts)

if not FROM_JSON:
    passed_cut_by_type = {}
    passed_cut_ids_with_type = np.array([])
    for i, (metadata_path, lcdata_path) in enumerate(zip(METADATA_PATHS, LCDATA_PATHS)):
        print("processing file {}".format(i))
        print(metadata_path.split("/")[-1], lcdata_path.split("/")[-1])
        metadata = pd.read_csv(metadata_path, compression="gzip") if os.path.splitext(metadata_path)[1] == ".gz" else pd.read_csv(metadata_path)
        lcdata = pd.read_csv(lcdata_path, compression="gzip") if os.path.splitext(lcdata_path)[1] == ".gz" else pd.read_csv(lcdata_path)
        lcdata = Table.from_pandas(lcdata)
        lcdata.add_index('object_id')
        passed_cut_current = apply_cuts(metadata, lcdata, [10000, 5, 10, 30])
        #[50, 5, 10, 30] thresholds = [time to first detection <= 50, num detections >= 5, snr > 10, active time >= 30 days]
        passed_cut_ids_with_type = np.concatenate((passed_cut_ids_with_type, passed_cut_current))
        for sn_id in passed_cut_current:
            sn_type, _ = str(sn_id).split("_")
            if sn_type in passed_cut_by_type:
                passed_cut_by_type[sn_type].append(str(sn_id))
            else:
                passed_cut_by_type[sn_type] = [str(sn_id)]
        if SAVE_TO_JSON:
            with open("{}/passed_cuts_{}.json".format(OUTPUT_PATH, i), "w") as f:
                json.dump(passed_cut_by_type, f)

    if SAVE_TO_JSON:
        with open("{}/passed_cuts.json".format(OUTPUT_PATH), "w") as f:
            json.dump(passed_cut_by_type, f)
else:
    with open("{}/passed_cuts.json".format(OUTPUT_PATH), "r") as infile:
        passed_cut_by_type = json.load(infile)

if IA_FRACTION == "categorical":
    passed_cut_num_by_type = {k: len(v) for k, v in passed_cut_by_type.items()}
    sorted_types = [k for k, _ in sorted(passed_cut_num_by_type.items(), key=lambda item: item[1])]

    least_sn_type = sorted_types[0]
    while passed_cut_num_by_type[least_sn_type] < CATEGORICAL_MIN_PER_TYPE: # to make the total ~1000
        sorted_types.remove(least_sn_type)
        least_sn_type = sorted_types[0]
    least_sn_type_num = CATEGORICAL_MAX_PER_TYPE if passed_cut_num_by_type[least_sn_type] > CATEGORICAL_MAX_PER_TYPE else passed_cut_num_by_type[least_sn_type] # to not make too many

    print("all types: {}".format(passed_cut_num_by_type))
    print("least type: {}, num: {}".format(least_sn_type, least_sn_type_num))

    heatmaps_final = np.array([])
    for sn_type in sorted_types:
        chosen_ids = np.random.choice(passed_cut_by_type[sn_type], least_sn_type_num, replace=False)
        chosen_ids_bytes = [np.string_(sn_id[2:-1]) for sn_id in chosen_ids]
        heatmaps_final = np.concatenate((heatmaps_final, chosen_ids_bytes))
    print("number of each type: {}".format(least_sn_type_num))
    print("total heatmaps: {:,}, total unique heatmaps: {:,}".format(len(heatmaps_final), len(np.unique(heatmaps_final))))
else:
    Ia_heatmaps = np.unique([id for id in passed_cut_ids_with_type if b"Ia_" in id])
    non_Ia_heatmaps = np.unique([id for id in passed_cut_ids_with_type if b"Ia_" not in id])

    total_heatmap_count = len(Ia_heatmaps) + len(non_Ia_heatmaps)
    print("total passed cut heatmaps: {}".format(total_heatmap_count))
    current_Ia_fraction = float(len(Ia_heatmaps)) / total_heatmap_count

    fraction = IA_FRACTION if IA_FRACTION < current_Ia_fraction else 1-IA_FRACTION
    heatmaps_to_change = Ia_heatmaps if IA_FRACTION < current_Ia_fraction else non_Ia_heatmaps
    unchanged_heatmaps = non_Ia_heatmaps if IA_FRACTION < current_Ia_fraction else Ia_heatmaps

    num_to_remove = (len(heatmaps_to_change) - fraction*total_heatmap_count)/(1 - fraction)
    num_to_keep = int(len(heatmaps_to_change) - num_to_remove)
    heatmaps_final = np.concatenate((unchanged_heatmaps, np.random.choice(heatmaps_to_change, num_to_keep, replace=False)))

    Ia_heatmaps = [id for id in heatmaps_final if b"Ia_" in id]
    non_Ia_heatmaps = [id for id in heatmaps_final if b"Ia_" not in id]
    print("number of type Ia heatmaps: {:,}, number of non-Ia heatmaps: {:,}".format(len(Ia_heatmaps), len(non_Ia_heatmaps)))
    print("total heatmaps: {:,}, total unique heatmaps: {:,}".format(len(heatmaps_final), len(np.unique(heatmaps_final))))

f = h5py.File("{}/{}_Ia_split_heatmaps_ids.hdf5".format(OUTPUT_PATH, str(IA_FRACTION).replace(".", "_")), "w")
f.create_dataset("names", data=heatmaps_final)
f.close()