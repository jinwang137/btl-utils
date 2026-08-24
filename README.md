# Contents
- [Contents](#contents)
    - [Database tunnel](#database-tunnel)
    - [Get module and part information from database](#get-module-and-part-information-from-database)
    - [Module summaries](#module-summaries)
        - [SM summary examples](#sm-summary-examples)
            - [Plot](#plot)
            - [Pair SMs](#pair-sms)
        - [DM summary examples](#dm-summary-examples)
            - [Plot](#plot-1)
            - [Group DMs](#group-dms)
    - [Module progress](#module-progress)
    - [Create tar file with results](#create-tar-file-with-results)


## Database tunnel
`./scripts/start_db_tunnel.sh <lxplus username>`

## Get module and part information from database

* Create the script for your BAC (under `scripts/<BAC>`) if not already there. For e.g.
  - `./scripts/CIT/get_sipm_info.py`
  - `./scripts/CIT/get_sm_info.py`
  - `./scripts/CIT/get_dm_info.py`
  
* Make BAC specific changes, for example:
  ```python
  utils.save_all_part_info(
    parttype = constants.SM.KIND_OF_PART,
    outyamlfile = "info/CIT/sm_info.yaml",
    inyamlfile = "info/CIT/sm_info.yaml",
    location_id = constants.LOCATION.CIT,
    ret = False
  )
  ```
  
* `<BAC> = CIT, UVA, MIB, PKU`
* Run the scripts to get the information from the database

## Module summaries

* Recommended: get the module and parts information from the databse first
* Create your module configuration yaml under `configs/<BAC>`
* Examples can be found under `configs/CIT`
* For summary plots with barcodes (for e.g. light output vs. SM barcode), you may have to change the barcode prefix in the configuration
* Run `/python/summarize_modules.py --help` to see explanations for the arguments

### SM summary examples

#### Plot
```bash
./python/summarize_modules.py \
--srcs "/path/to/dir/with/runs/**:run(?P<run>\d+)/module_(?P<barcode>\d+)_analysis.root" \
--moduletype SensorModule \
--plotcfg configs/CIT/config_sm_summary.yaml \
--catcfg configs/CIT/config_sm_categorization_na.yaml \
--outdir results/sm_summary \
--skipmodules info/CIT/skip_sms.txt \
--sminfo info/CIT/sm_info.yaml \
--location <BAC>
```

#### Pair SMs
```bash
./python/summarize_modules.py \
--srcs "/path/to/dir/with/runs/**:run(?P<run>\d+)/module_(?P<barcode>\d+)_analysis.root" \
--moduletype SensorModule \
--catcfg configs/CIT/config_sm_categorization_na.yaml \
--outdir results/sm_pairing \
--sminfo info/CIT/sm_info.yaml \
--dminfo info/CIT/dm_info.yaml \
--pairsms \
--mixsmcats \
--location <BAC>
```

### DM summary examples

#### Plot
```bash
./python/summarize_modules.py \
--srcs "/path/to/dir/with/runs/**:run-(?P<run>\d+)_DM-(?P<barcode>\d+).root" \
--moduletype DetectorModule \
--plotcfg configs/CIT/config_dm_summary.yaml \
--catcfg configs/CIT/config_dm_categorization.yaml \
--outdir results/dm_summary \
--sipminfo info/CIT/sipm_info.yaml \
--sminfo info/CIT/sm_info.yaml \
--dminfo info/CIT/dm_info.yaml \
--smresults <path/to/your/sm_summary/module_categorization.yaml> \
--location <BAC>
```

#### Group DMs
```bash
--srcs "/path/to/dir/with/runs/**:run-(?P<run>\d+)_DM-(?P<barcode>\d+).root" \
--moduletype DetectorModule \
--catcfg configs/CIT/config_dm_categorization.yaml \
--outdir results/CIT/dm_grouping \
--sipminfo info/CIT/sipm_info.yaml \
--sminfo info/CIT/sm_info.yaml \
--dminfo info/CIT/dm_info.yaml \
--ruinfo info/CIT/ru_info.yaml \
--smresults <path/to/your/sm_summary/module_categorization.yaml> \
--groupdms \
--location <BAC>
```


## Module progress
```bash
./python/plot_module_progress.py \
--moduletypes SensorModule DetectorModule \
--locations CIT MIB PKU UVA \
--outdir results/module_progress
```


## Create tar file with results

Update tar file with new results in directory:<br>
`./scripts/archive_dir.sh <directory>`



## Combine Summary from All BACs
```bash
python btl-utils-main/python/combine_bac_<sm/dm>_summary_roots.py \
--CIT <CIT/sm_summary/> \ 
--UVA <UVA/sm_summary/> \ 
--MIB <MIB/sm_summary/> \ 
--PKU <PKU/sm-summary/> \
--outdir <outdir>
```
