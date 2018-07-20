Infortrend Cinder Driver
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

# Infortrend Cinder Driver (FC and iSCSI)

## Overview
Infortrend implement ISCSI and FC volume drivers for OpenStack Cinder.
It manages storage by Infortrend CLI tool.

## Support OpenStack Version

- Release on Openstack Liberty and later.
  + It is already merged into Liberty. [More detail](https://blueprints.launchpad.net/cinder/+spec/infortrend-iscsi-fc-volume-driver).
- For the latest driver version, please check [release](https://github.com/infortrend-openstack/infortrend-cinder-driver/releases).

## Supported Cinder Operations

- Create, delete, attach, and detach volumes.
- Create and delete a snapshot.
- Create a volume from a snapshot.
- Copy an image to a volume.
- Copy a volume to an image.
- Clone a volume.
- Extend a volume
- Retype a volume.
- Migrate a volume with back-end assistance.
- Live migrate an instance with volumes hosted on an Infortrend backend.
- List, manage and unmanage a volume.
- List, manage and unmanage a snapshot.

## How to setup and use

- If Cinder runs on Ubuntu, run `. setupIFTDriver.sh` to quick update Cinder-volume with this Cinder Driver.
- Please check our [user manual](https://github.com/infortrend-openstack/openstack-cinder-manaul).

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
