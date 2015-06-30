
## 2015/06/30, Version 1.0.1

#### Notable changes
- Manage Existing bug: 
  + For infortrend driver, it should update provider_location information (partition id and system id). Otherwise, the volume would miss the infortrend partition after importing partition.
- DS4000 bug:
  + For DS4000, we need to use 'BID' to get the wwpn information because target ID was not 112 or 113 on DS4000. It is compatible with other infortrend product.

#### Related Patch
- [194524](https://review.openstack.org/#/c/194524/) - Fix getting wwpn information in infortrend driver for DS4000
- [194519](https://review.openstack.org/#/c/194519/) - Fix manage_existing function in infortrend driver

## 2015/06/18, Version 1.0.0

It is the version which is merged into cinder.
https://review.openstack.org/#/c/177113/

Infortrend implement ISCSI and FC volume drivers for EonStor DS product.
It manages storage by Infortrend CLI tool.

common_cli.py implements the basic Cinder Driver API.
infortrend_fc_cli.py and infortrend_iscsi_cli.py use them to provide FC and iSCSI specific support.

Support features:
- Volume Create/Delete
- Volume Attach/Detach
- Snapshot Create/Delete
- Create Volume from Snapshot
- Get Volume Stats
- Copy Image to Volume
- Copy Volume to Image
- Clone Volume
- Extend Volume
- Volume Manage/Unmanage
