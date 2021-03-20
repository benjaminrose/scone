import os, sys
import yaml
import argparse
import create_heatmaps_utils
from multiprocessing import Process

# TODO: give people the option to use sbatch instead of MP? but how to create system-agnostic sbatch header

parser = argparse.ArgumentParser(description='create heatmaps from lightcurve data')
parser.add_argument('--config_path', type=str, help='absolute or relative path to your yml config file, i.e. "/user/files/create_heatmaps_config.yml"')
args = parser.parse_args()

def load_config(config_path):
    with open(config_path, "r") as cfgfile:
        config = yaml.load(cfgfile)
    return config

config = load_config(args.config_path)
if "input_path" in config:
    config['metadata_paths'] = [f.path for f in os.scandir(config["input_path"]) if "HEAD.csv" in f.name]
    config['lcdata_paths'] = [path.replace("HEAD", "PHOT") for path in config['metadata_paths']]

num_paths = len(config["lcdata_paths"])

procs = []
for i in range(num_paths):
    proc = Process(target=create_heatmaps_utils.run, args=(config, i))
    proc.start()
    procs.append(proc)
for proc in procs:
    proc.join() # wait until procs are done

failed_procs = []
for i, proc in enumerate(procs):
    if proc.exitcode != 0:
        failed_procs.append(i)

if len(failed_procs) == 0:
    donefile_info = "SUCCESS"
    exit_code = 0
else:
    donefile_info = "CREATE HEATMAPS FAILURE\nindices of failed create heatmaps jobs: {}\ncheck out the LC data files or metadata files at those indices in the config yml at {}\nlogs located at create_heatmaps_i.log, i=failed index".format(failed_procs, args.config_path)
    exit_code = 1

with open(config["donefile"], "w+") as donefile:
    donefile.write(donefile_info)

sys.exit(exit_code)
