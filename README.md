Eonstor DS Cinder Driver
=============
| Branch  | Unit Test Status |
| ------- | ------------ |
| current | [![Travis branch][travis-ci-img]][travis-ci-url] |
| master  | [![Travis branch][travis-ci-master-img]][travis-ci-master-url] |
| develop | [![Travis branch][travis-ci-dev-img]][travis-ci-dev-url] |

Copyright (c) 2015 Infortrend Technology, Inc. All Rights Reserved.

Licensed under the Apache License, Version 2.0 (the "License"); you may
not use this file except in compliance with the License. You may obtain
a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations
under the License.

# EonStor DS Driver (FC and iSCSI)

## Overview
Infortrend implement ISCSI and FC volume drivers for EonStor DS product.
It manages storage by Infortrend CLI tool.

## Support OpenStack Version

- Base on Kilo.
  + If you want to run on Kilo, please download from [release](https://github.com/infortrend-openstack/eonstor-ds-cinder-driver/releases).
- Release on Liberty.
  + It is already merged into Liberty. [More detail](https://blueprints.launchpad.net/cinder/+spec/infortrend-iscsi-fc-volume-driver).

## Supported Cinder Operations

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

## Require Tools

- Infortrend CLI, please download from [release](https://github.com/infortrend-openstack/eonstor-ds-cinder-driver/releases).

# Run Test

Execute Bash file and it would git clone cinder driver to run unit test.
```
./run_test.sh
```

[travis-ci-img]: https://img.shields.io/travis/infortrend-openstack/infortrend-cinder-driver.svg?style=flat-square
[travis-ci-url]: https://travis-ci.org/infortrend-openstack/infortrend-cinder-driver

[travis-ci-master-img]: https://img.shields.io/travis/infortrend-openstack/infortrend-cinder-driver/master.svg?style=flat-square
[travis-ci-master-url]: https://travis-ci.org/infortrend-openstack/infortrend-cinder-driver/branches

[travis-ci-dev-img]: https://img.shields.io/travis/infortrend-openstack/infortrend-cinder-driver/develop.svg?style=flat-square
[travis-ci-dev-url]: https://travis-ci.org/infortrend-openstack/infortrend-cinder-driver/branches
