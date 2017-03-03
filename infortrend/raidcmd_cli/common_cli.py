# Copyright (c) 2015 Infortrend Technology, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
"""
Infortrend Common CLI.
"""
import math
import os
import time

from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import timeutils
from oslo_utils import units

from cinder import exception
from cinder.i18n import _
from cinder.i18n import _LE
from cinder.i18n import _LI
from cinder.i18n import _LW
from cinder.volume.drivers.infortrend.raidcmd_cli import cli_factory as cli
from cinder.volume.drivers.san import san
from cinder.volume import volume_types
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)

infortrend_esds_opts = [
    cfg.StrOpt('infortrend_pools_name',
               default='',
               help='The Infortrend logical volumes name list. '
               'It is separated with comma.'),
    cfg.StrOpt('infortrend_cli_path',
               default='/opt/bin/Infortrend/raidcmd_ESDS10.jar',
               help='The Infortrend CLI absolute path.'),
    cfg.IntOpt('infortrend_cli_max_retries',
               default=5,
               help='The maximum retry times if a command fails.'),
    cfg.IntOpt('infortrend_cli_timeout',
               default=60,
               help='The timeout for CLI in seconds.'),
    cfg.IntOpt('infortrend_migration_timeout',
               default=30,
               help='The timeout for migration jobs in minutes.'),
    cfg.StrOpt('infortrend_slots_a_channels_id',
               default='',
               help='Infortrend raid channel ID list on Slot A '
               'for OpenStack usage. It is separated with comma.'),
    cfg.StrOpt('infortrend_slots_b_channels_id',
               default='',
               help='Infortrend raid channel ID list on Slot B '
               'for OpenStack usage. It is separated with comma.'),
    cfg.StrOpt('infortrend_iqn_prefix',
               default='iqn.2002-10.com.infortrend',
               help='Infortrend iqn prefix for iSCSI.'),
    cfg.BoolOpt('infortrend_cli_cache',
                default=False,
                help='The Infortrend CLI cache. '
                'Make sure the array is only managed by Openstack, '
                'and it is only used by one cinder-volume node. '
                'Otherwise, never enable it! '
                'The data might be asynchronous '
                'if there were any other operations.'),
    cfg.StrOpt('java_path',
               default='/usr/bin/java',
               help='The Java absolute path.'),
]

CONF = cfg.CONF
CONF.register_opts(infortrend_esds_opts)

CLI_RC_FILTER = {
    'CreatePartition': {'error': _('Failed to create partition.')},
    'DeletePartition': {'error': _('Failed to delete partition.')},
    'SetPartition': {'error': _('Failed to set partition.')},
    'CreateMap': {
        'warning': {20: _LW('The MCS Channel is grouped.')},
        'error': _('Failed to create map.'),
    },
    'DeleteMap': {
        'warning': {11: _LW('No mapping.')},
        'error': _('Failed to delete map.'),
    },
    'CreateSnapshot': {'error': _('Failed to create snapshot.')},
    'DeleteSnapshot': {'error': _('Failed to delete snapshot.')},
    'CreateReplica': {'error': _('Failed to create replica.')},
    'DeleteReplica': {'error': _('Failed to delete replica.')},
    'CreateIQN': {
        'warning': {20: _LW('IQN already existed.')},
        'error': _('Failed to create iqn.'),
    },
    'DeleteIQN': {
        'warning': {
            20: _LW('IQN has been used to create map.'),
            11: _LW('No such host alias name.'),
        },
        'error': _('Failed to delete iqn.'),
    },
    'ShowLV': {'error': _('Failed to get lv info.')},
    'ShowPartition': {'error': _('Failed to get partition info.')},
    'ShowSnapshot': {'error': _('Failed to get snapshot info.')},
    'ShowDevice': {'error': _('Failed to get device info.')},
    'ShowChannel': {'error': _('Failed to get channel info.')},
    'ShowMap': {'error': _('Failed to get map info.')},
    'ShowNet': {'error': _('Failed to get network info.')},
    'ShowLicense': {'error': _('Failed to get license info.')},
    'ShowReplica': {'error': _('Failed to get replica info.')},
    'ShowWWN': {'error': _('Failed to get wwn info.')},
    'ShowIQN': {'error': _('Failed to get iqn info.')},
    'ShowHost': {'error': _('Failed to get host info.')},
    'SetIOTimeout': {'error': _('Failed to set IO timeout.')},
    'ConnectRaid': {'error': _('Failed to connect to raid.')},
    'ExecuteCommand': {'error': _('Failed to execute common command.')},
    'ShellCommand': {'error': _('Failed to execute shell command.')},
}


def log_func(func):
    def inner(self, *args, **kwargs):
        LOG.debug('Entering: %(method)s', {'method': func.__name__})
        start = timeutils.utcnow()
        ret = func(self, *args, **kwargs)
        end = timeutils.utcnow()
        LOG.debug(
            'Leaving: %(method)s, '
            'Spent: %(time)s sec, '
            'Return: %(ret)s.', {
                'method': func.__name__,
                'time': timeutils.delta_seconds(start, end),
                'ret': ret})
        return ret
    return inner


def mi_to_gi(mi_size):
    return mi_size * units.Mi / units.Gi


def gi_to_mi(gi_size):
    return gi_size * units.Gi / units.Mi


def ti_to_gi(ti_size):
    return ti_size * units.Ti / units.Gi


def ti_to_mi(ti_size):
    return ti_size * units.Ti / units.Mi


class InfortrendCommon(object):

    """The Infortrend's Common Command using CLI.

    Version history:
        1.0.0 - Initial driver
        1.0.1 - Support DS4000
        1.0.2 - Support GS/GSe Family
        1.0.3 - Add iSCSI MPIO support
        1.0.4 - Fix Nova live migration (bug #1481968)
        1.1.0 - Improve driver performance
        1.1.1 - Fix creating volume on the wrong pool
              - Fix manage-existing issues
        1.1.2 - Add volume migration check
        2.0.0 - Enhance extraspecs usage and refactor retype
        2.0.1 - Remove checks while deleting volume
    """

    VERSION = '2.0.1'

    constants = {
        'ISCSI_PORT': 3260,
        'MAX_LUN_MAP_PER_CHL': 128,
    }

    PROVISIONING_KEY = 'infortrend:provisioning'
    TIERING_SET_KEY = 'infortrend:tiering'

    PROVISIONING_VALUES = ['thin', 'full']

    def __init__(self, protocol, configuration=None):

        self.protocol = protocol
        self.configuration = configuration
        self.configuration.append_config_values(san.san_opts)
        self.configuration.append_config_values(infortrend_esds_opts)

        self.path = self.configuration.infortrend_cli_path
        self.password = self.configuration.san_password
        self.ip = self.configuration.san_ip
        self.cli_retry_time = self.configuration.infortrend_cli_max_retries
        self.cli_timeout = self.configuration.infortrend_cli_timeout
        self.migrate_timeout = self.configuration.infortrend_migration_timeout
        self.cli_cache = self.configuration.infortrend_cli_cache
        self.iqn_prefix = self.configuration.infortrend_iqn_prefix
        self.iqn = self.iqn_prefix + ':raid.uid%s.%s%s%s'
        self.unmanaged_prefix = 'cinder-unmanaged-%s'
        self.java_path = self.configuration.java_path

        if self.ip == '':
            msg = _('san_ip is not set.')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        if self.cli_timeout < 40:
            msg = _('infortrend_cli_timeout should be larger than 40.')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        self.fc_lookup_service = fczm_utils.create_lookup_service()

        self.backend_name = None
        self._volume_stats = None
        self.system_id = None
        self.pid = None
        self.fd = None
        self._model_type = 'R'
        self._replica_timeout = self.migrate_timeout * 60

        self.map_dict = {
            'slot_a': {},
            'slot_b': {},
        }
        self.map_dict_init = False

        self.target_dict = {
            'slot_a': {},
            'slot_b': {},
        }

        if self.protocol == 'iSCSI':
            self.mcs_dict = {
                'slot_a': {},
                'slot_b': {},
            }

        self.tier_pools_dict = {}

        self._init_pool_list()
        self._init_channel_list()
        self._init_raidcmd()
        self.cli_conf = {
            'path': self.path,
            'cli_retry_time': self.cli_retry_time,
            'raidcmd_timeout': self.cli_timeout,
            'cli_cache': self.cli_cache,
            'pid': self.pid,
            'fd': self.fd,
        }
        self._init_raid_connection()
        self._set_raidcmd()

    def _init_pool_list(self):
        pools_name = self.configuration.infortrend_pools_name
        if pools_name == '':
            msg = _('Pools name is not set.')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        tmp_pool_list = pools_name.split(',')
        self.pool_list = [pool.strip() for pool in tmp_pool_list]

    def _init_channel_list(self):
        self.channel_list = {
            'slot_a': [],
            'slot_b': [],
        }
        tmp_channel_list = (
            self.configuration.infortrend_slots_a_channels_id.split(',')
        )
        self.channel_list['slot_a'] = (
            [channel.strip() for channel in tmp_channel_list]
        )
        tmp_channel_list = (
            self.configuration.infortrend_slots_b_channels_id.split(',')
        )
        self.channel_list['slot_b'] = (
            [channel.strip() for channel in tmp_channel_list]
        )

    def _init_raidcmd(self):
        if not self.pid:
            self.pid, self.fd = os.forkpty()
            if self.pid == 0:
                os.execv(self.java_path, [self.java_path, '-jar', self.path])

            check_java_start = cli.os_read(self.fd, 1024, 'RAIDCmd:>', 10)
            if 'Raidcmd timeout' in check_java_start:
                msg = _('Raidcmd failed to start. '
                        'Please check Java is installed.')
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)
        LOG.debug('Raidcmd [%s:%s] start!' % (self.pid, self.fd))

    def _set_raidcmd(self):
        cli_io_timeout = str(self.cli_timeout - 10)
        rc, _ = self._execute('SetIOTimeout', cli_io_timeout)
        LOG.debug('CLI IO timeout is [%s]', cli_io_timeout)

    def _init_raid_connection(self):
        raid_password = ''
        if self.password:
            raid_password = 'password=%s' % self.password

        rc, _ = self._execute('ConnectRaid', self.ip, raid_password)
        LOG.info(_LI('Raid [%s] is connected!'), self.ip)

    def _execute_command(self, cli_type, *args, **kwargs):
        command = getattr(cli, cli_type)
        return command(self.cli_conf).execute(*args, **kwargs)

    def _execute(self, cli_type, *args, **kwargs):
        LOG.debug('Executing command type: %(type)s.', {'type': cli_type})

        @lockutils.synchronized('raidcmd-%s' % self.pid, 'infortrend-', False)
        def _lock_raidcmd(cli_type, *args, **kwargs):
            return self._execute_command(cli_type, *args, **kwargs)

        rc, out = _lock_raidcmd(cli_type, *args, **kwargs)

        if rc != 0:
            if cli_type == 'CheckConnection':
                return rc, out
            elif ('warning' in CLI_RC_FILTER[cli_type] and
                    rc in CLI_RC_FILTER[cli_type]['warning']):
                LOG.warning(CLI_RC_FILTER[cli_type]['warning'][rc])
            else:
                msg = CLI_RC_FILTER[cli_type]['error']
                LOG.error(msg)
                raise exception.InfortrendCliException(
                    err=msg, param=args, rc=rc, out=out)
        return rc, out

    @log_func
    def _init_map_info(self):
        if not self.map_dict_init:

            rc, channel_info = self._execute('ShowChannel')

            if 'BID' in channel_info[0]:
                self._model_type = 'R'
                self._set_channel_id(channel_info, 'slot_b')
            else:
                self._model_type = 'G'

            self._set_channel_id(channel_info, 'slot_a')

            self.map_dict_init = True

        for controller in sorted(self.map_dict.keys()):
            LOG.debug('Controller: [%(controller)s] '
                      'enable channels: %(ch)s', {
                          'controller': controller,
                          'ch': sorted(self.map_dict[controller].keys())})

    @log_func
    def _update_map_info(self, multipath=False):
        """Record the driver mapping information.

        map_dict = {
            'slot_a': {
                '0': [1, 2, 3, 4]  # Slot A Channel 0 map lun 1, 2, 3, 4
            },
            'slot_b' : {
                '1': [0, 1, 3]     # Slot B Channel 1 map lun 0, 1, 3
            }
        }
        """
        rc, map_info = self._execute('ShowMap')

        self._update_map_info_by_slot(map_info, 'slot_a')

        if multipath and self._model_type == 'R':
            self._update_map_info_by_slot(map_info, 'slot_b')

        return map_info

    @log_func
    def _update_map_info_by_slot(self, map_info, slot_key):
        for key, value in self.map_dict[slot_key].items():
            self.map_dict[slot_key][key] = list(
                range(self.constants['MAX_LUN_MAP_PER_CHL']))

        if len(map_info) > 0 and isinstance(map_info, list):
            for entry in map_info:
                ch = entry['Ch']
                lun = entry['LUN']
                if ch not in self.map_dict[slot_key].keys():
                    continue

                target_id = self.target_dict[slot_key][ch]
                if (entry['Target'] == target_id and
                        int(lun) in self.map_dict[slot_key][ch]):
                    self.map_dict[slot_key][ch].remove(int(lun))

    def _check_initiator_has_lun_map(self, initiator_info):
        rc, map_info = self._execute('ShowMap')

        if not isinstance(initiator_info, list):
            initiator_info = (initiator_info,)
        if len(map_info) > 0:
            for initiator_name in initiator_info:
                for entry in map_info:
                    if initiator_name.lower() == entry['Host-ID'].lower():
                        return True
        return False

    @log_func
    def _set_channel_id(
            self, channel_info, controller):

        if self.protocol == 'iSCSI':
            check_channel_type = ('NETWORK', 'LAN')
        else:
            check_channel_type = ('FIBRE', 'Fibre')

        for entry in channel_info:
            if entry['Type'] in check_channel_type:
                if entry['Ch'] in self.channel_list[controller]:
                    self.map_dict[controller][entry['Ch']] = []

                    if self.protocol == 'iSCSI':
                        self._update_mcs_dict(
                            entry['Ch'], entry['MCS'], controller)

                    self._update_target_dict(entry, controller)

                    # check the channel status
                    if entry['curClock'] == '---':
                        LOG.warning(_LW(
                            'Controller[%(controller)s] '
                            'Channel[%(Ch)s] not linked, please check.'), {
                                'controller': controller, 'Ch': entry['Ch']})

    @log_func
    def _update_target_dict(self, channel, controller):
        """Record the target id for mapping.

        # R model
        target_dict = {
            'slot_a': {
                '0': '0',
                '1': '0',
            },
            'slot_b': {
                '0': '1',
                '1': '1',
            },
        }

        # G model
        target_dict = {
            'slot_a': {
                '2': '32',
                '3': '112',
            }
        }
        """
        if self._model_type == 'G':
            self.target_dict[controller][channel['Ch']] = channel['ID']
        else:
            if controller == 'slot_a':
                self.target_dict[controller][channel['Ch']] = channel['AID']
            else:
                self.target_dict[controller][channel['Ch']] = channel['BID']

    def _update_mcs_dict(self, channel_id, mcs_id, controller):
        """Record the iSCSI MCS topology.

        # R model with mcs, but it not working with iSCSI multipath
        mcs_dict = {
            'slot_a': {
                '0': ['0', '1'],
                '2': ['2'],
                '3': ['3'],
            },
            'slot_b': {
                '0': ['0', '1'],
                '2': ['2']
            }
        }

        # G model with mcs
        mcs_dict = {
            'slot_a': {
                '0': ['0', '1'],
                '1': ['2']
            },
            'slot_b': {}
        }
        """
        if mcs_id not in self.mcs_dict[controller]:
            self.mcs_dict[controller][mcs_id] = []
        self.mcs_dict[controller][mcs_id].append(channel_id)

    def _check_pools_setup(self):
        pool_list = self.pool_list[:]

        rc, lv_info = self._execute('ShowLV')

        for lv in lv_info:
            if lv['Name'] in pool_list:
                pool_list.remove(lv['Name'])
            if len(pool_list) == 0:
                break

        if len(pool_list) != 0:
            msg = _('Please create %(pool_list)s pool in advance!') % {
                'pool_list': pool_list}
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

    def _check_host_setup(self):
        rc, host_info = self._execute('ShowHost')
        max_lun = int(host_info[0]['Max LUN per ID'])
        device_type = host_info[0]['Peripheral device type']

        if 'No Device Present' not in device_type:
            msg = _('Please set <Peripheral device type> to '
                    '<No Device Present (Type=0x7f)> in advance!')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        self.constants['MAX_LUN_MAP_PER_CHL'] = max_lun
        system_id = self._get_system_id(self.ip)
        LOG.info(_LI('Device: [%(device)s] '
                     'max LUN setting is: [%(luns)s]'), {
                         'device': system_id,
                         'luns': self.constants['MAX_LUN_MAP_PER_CHL']})

    def check_for_setup_error(self):
        self._check_pools_setup()
        self._check_host_setup()

    def create_volume(self, volume):
        """Create a Infortrend partition."""
        volume_id = volume['id'].replace('-', '')

        self._create_partition_by_default(volume)
        part_id = self._get_part_id(volume_id)

        system_id = self._get_system_id(self.ip)

        model_dict = {
            'system_id': system_id,
            'partition_id': part_id,
        }

        model_update = {
            "provider_location": self._concat_provider_location(model_dict),
        }
        LOG.info(_LI('Create Volume %(volume_id)s completed.'), {
            'volume_id': volume_id})
        return model_update

    def _create_partition_by_default(self, volume):
        pool_id = self._get_volume_pool_id(volume)
        self._create_partition_with_pool(volume, pool_id)

    def _create_partition_with_pool(
            self, volume, pool_id, extraspecs=None):

        volume_id = volume['id'].replace('-', '')
        volume_size = gi_to_mi(volume['size'])
        pool_name = volume['host'].split('#')[-1]

        if extraspecs:
            extraspecs = self._get_extraspecs_set(extraspecs)
        else:
            extraspecs = self._get_volume_type_extraspecs(volume)

        pool_extraspecs = self._get_pool_extraspecs(pool_name, extraspecs)
        provisioning = pool_extraspecs['provisioning']
        tiering = pool_extraspecs['tiering']

        extraspecs_dict = {}
        # Normal pool
        if pool_id not in self.tier_pools_dict.keys():
            if provisioning == 'thin':
                extraspecs_dict['provisioning'] = int(volume_size * 0.2)
                extraspecs_dict['init'] = 'disable'
        # Tier pool
        else:
            pool_tiers = self.tier_pools_dict[pool_id]
            if tiering == 'all':
                # thin provisioning reside on all tiers
                if provisioning == 'thin':
                    extraspecs_dict['provisioning'] = 0
                    tiering_set = ','.join(str(i) for i in pool_tiers)
                    extraspecs_dict['tiering'] = tiering_set
                    extraspecs_dict['init'] = 'disable'
                # full provisioning reside on the top tier
                else:
                    top_tier = self.tier_pools_dict.get(pool_id)[0]
                    self._check_tier_space(top_tier, pool_id, volume_size)
                    extraspecs_dict['tiering'] = str(top_tier)
            else:
                # check extraspecs fit the real pool tiers
                if not self._check_pool_tiering(pool_tiers, tiering):
                    msg = _('Tiering extraspecs %(pool_name)s:%(tiering)s '
                            'can not fit in the real tiers %(pool_tier)s.') % {
                                'pool_name': pool_name,
                                'tiering': tiering,
                                'pool_tier': pool_tiers}
                    LOG.error(msg)
                    raise exception.VolumeDriverException(message=msg)
                # User specific tier levels
                if provisioning == 'thin':
                    extraspecs_dict['provisioning'] = 0
                    tiering_set = ','.join(str(i) for i in tiering)
                    extraspecs_dict['tiering'] = tiering_set
                    extraspecs_dict['init'] = 'disable'
                else:
                    self._check_tier_space(tiering[0], pool_id, volume_size)
                    extraspecs_dict['tiering'] = str(tiering[0])

        cmd = ''
        if extraspecs_dict:
            cmd = self._create_part_parameters_str(extraspecs_dict)

        commands = (pool_id, volume_id, 'size=%s' % int(volume_size), cmd)
        self._execute('CreatePartition', *commands)

    def _check_pool_tiering(self, pool_tiers, extra_specs_tiers):
        return set(extra_specs_tiers).issubset(pool_tiers)

    def _check_tier_pool_or_not(self, pool_id):
        if pool_id in self.tier_pools_dict.keys():
            return True
        return False

    def _check_tier_space(self, tier_level, pool_id, volume_size):
        rc, lv_info = self._execute('ShowLV', 'tier')
        if lv_info:
            for entry in lv_info:
                if (entry['LV-ID'] == pool_id and
                        int(entry['Tier']) == tier_level):
                    total_space = self._parse_size(entry['Size'], 'MB')
                    used_space = self._parse_size(entry['Used'], 'MB')
                    if not (total_space and used_space):
                        return
                    elif volume_size > (total_space - used_space):
                        LOG.warning(_LW('Tier pool [%(pool_id)s] '
                                        'has already run out of space in '
                                        'tier level [%(tier_level)s].'), {
                                            'pool_id': pool_id,
                                            'tier_level': tier_level})

    def _parse_size(self, size_string, return_unit):
        size = float(size_string.split(' ', 1)[0])
        if 'TB' in size_string:
            if return_unit == 'GB':
                return round(ti_to_gi(size), 2)
            elif return_unit == 'MB':
                return round(ti_to_mi(size))
        elif 'GB' in size_string:
            if return_unit == 'GB':
                return round(size, 2)
            elif return_unit == 'MB':
                return round(gi_to_mi(size))
        elif 'MB' in size_string:
            if return_unit == 'GB':
                return round(mi_to_gi(size), 2)
            elif return_unit == 'MB':
                return round(size)
        else:
            LOG.warning(_LW('Tier size [%(size_string)s], '
                            'the unit is not recognized.'), {
                                'size_string': size_string})
        return

    def _create_part_parameters_str(self, extraspecs_dict):
        parameters_list = []
        parameters = {
            'provisioning': 'min=%sMB',
            'tiering': 'tier=%s',
            'init': 'init=%s',
        }
        for extraspec in extraspecs_dict.keys():
            value = parameters[extraspec] % (extraspecs_dict[extraspec])
            parameters_list.append(value)

        return ' '.join(parameters_list)

    @log_func
    def _iscsi_create_map(
            self, part_id, channel_dict, lun_id, host, system_id):

        iqns = []
        ips = []
        luns = []
        host_filter = self._create_host_filter(host)
        rc, net_list = self._execute('ShowNet')
        rc, part_mapping = self._execute('ShowMap', 'part=%s' % part_id)

        for controller in sorted(channel_dict.keys()):
            for channel_id in sorted(channel_dict[controller]):
                target_id = self.target_dict[controller][channel_id]
                exist_lun_id = self._check_map(
                    channel_id, target_id, part_mapping, host)

                if exist_lun_id < 0:
                    commands = (
                        'part', part_id, channel_id, target_id, lun_id,
                        host_filter
                    )
                    rc, out = self._execute('CreateMap', *commands)
                    if rc != 0:
                        msg = _('Volume[%(part_id)s] create map failed, '
                                'Ch:[%(Ch)s] ID:[%(tid)s] LUN:[%(lun)s].') % {
                                    'part_id': part_id, 'Ch': channel_id,
                                    'tid': target_id, 'lun': lun_id}
                        LOG.error(msg)
                        raise exception.VolumeDriverException(message=msg)

                    exist_lun_id = int(lun_id)
                    self.map_dict[controller][channel_id].remove(exist_lun_id)

                mcs_id = self._get_mcs_id(channel_id, controller)
                # There might be some channels in the same group
                for channel in self.mcs_dict[controller][mcs_id]:
                    target_id = self.target_dict[controller][channel]
                    map_ch_info = {
                        'system_id': system_id,
                        'mcs_id': mcs_id,
                        'target_id': target_id,
                        'controller': controller,
                    }
                    iqns.append(self._generate_iqn(map_ch_info))
                    ips.append(self._get_ip_by_channel(
                        channel, net_list, controller))
                    luns.append(exist_lun_id)

        return iqns, ips, luns

    def _check_map(self, channel_id, target_id, part_map_info, host):
        if len(part_map_info) > 0:
            for entry in part_map_info:
                if (entry['Ch'] == channel_id and
                        entry['Target'] == target_id and
                        entry['Host-ID'].lower() == host.lower()):
                    return int(entry['LUN'])
        return -1

    def _create_host_filter(self, host):
        if self.protocol == 'iSCSI':
            host_filter = 'iqn=%s' % host
        else:
            host_filter = 'wwn=%s' % host
        return host_filter

    def _get_extraspecs_dict(self, volume_type_id):
        extraspecs = {}
        if volume_type_id:
            extraspecs = volume_types.get_volume_type_extra_specs(
                volume_type_id)

        return extraspecs

    def _get_volume_pool_id(self, volume):
        pool_name = volume['host'].split('#')[-1]
        pool_id = self._find_pool_id_by_name(pool_name)

        if pool_id is None:
            msg = _('Failed to get pool id with volume %(volume_id)s.') % {
                'volume_id': volume['id']}
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        return pool_id

    def _get_volume_type_extraspecs(self, volume):
        """Example for Infortrend extraspecs settings:

            Using a global setting:
                infortrend:provisoioning: 'thin'
                infortrend:tiering: '0,1,2'

            Using an individual setting:
                infortrend:provisoioning: 'LV0:thin;LV1:full'
                infortrend:tiering: 'LV0:0,1,3; LV1:1'

            Using a mixed setting:
                infortrend:provisoioning: 'LV0:thin;LV1:full'
                infortrend:tiering: 'all'
        """
        # extraspecs default setting
        extraspecs_set = {
            'global_provisioning': 'full',
            'global_tiering': 'all',
        }
        extraspecs = self._get_extraspecs_dict(volume['volume_type_id'])
        if extraspecs:
            extraspecs_set = self._get_extraspecs_set(extraspecs)
        return extraspecs_set

    def _get_pool_extraspecs(self, pool_name, all_extraspecs):
        LOG.debug('_Extraspecs_dict: %s', all_extraspecs)
        pool_extraspecs = {}
        provisioning = None
        tiering = None

        # check individual setting
        if pool_name in all_extraspecs.keys():
            if 'provisioning' in all_extraspecs[pool_name]:
                provisioning = all_extraspecs[pool_name]['provisioning']
            if 'tiering' in all_extraspecs[pool_name]:
                tiering = all_extraspecs[pool_name]['tiering']

        # use global setting
        if not provisioning:
            provisioning = all_extraspecs['global_provisioning']
        if not tiering:
            tiering = all_extraspecs['global_tiering']

        if tiering != 'all':
            pool_id = self._find_pool_id_by_name(pool_name)
            if not self._check_tier_pool_or_not(pool_id):
                LOG.warning(_LW('Infortrend pool: [%(pool_name)s] '
                                'is not a tier pool. Skip tiering '
                                '%(tiering)s because it is invalid.'), {
                                    'pool_name': pool_name,
                                    'tiering': tiering})
            self._check_extraspecs_conflict(tiering, provisioning)

        pool_extraspecs['provisioning'] = provisioning
        pool_extraspecs['tiering'] = tiering

        for key, value in pool_extraspecs.items():
            if 'Err' in value:
                err, user_setting = value.split(':', 1)
                msg = _('Extraspecs Error, '
                        'pool: [%(pool)s], %(key)s: %(setting)s '
                        'is invalid, please check.') % {
                            'pool': pool_name,
                            'key': key,
                            'setting': user_setting}
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)

        return pool_extraspecs

    def _check_extraspecs_conflict(self, tiering, provisioning):
        if len(tiering) > 1 and provisioning == 'full':
            msg = _('When provision is full, '
                    'it must specify only one tier instead of '
                    '%(tiering)s tiers.') % {
                        'tiering': tiering}
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

    def _get_extraspecs_set(self, extraspecs):
        """Return extraspecs settings dictionary

        Legal values:
            provisioning: 'thin', 'full'
            tiering: 'all' or combination of 0,1,2,3

        Only global settings example:
        extraspecs_set = {
            'global_provisioning': 'thin',
            'global_tiering': '[0, 1]',
        }

        All individual settings example:
        extraspecs_set = {
            'global_provisioning': 'full',
            'global_tiering': 'all',
            'LV0': {
                'provisioning': 'thin',
                'tiering': [0, 1, 3],
            },
            'LV1': {
                'provisioning': 'full',
                'tiering': [1],
            }
        }

        Mixed settings example:
        extraspecs_set = {
            'global_provisioning': 'thin',
            'global_tiering': 'all',
            'LV0': {
                'tiering': [0, 1, 3],
            },
            'LV1': {
                'provisioning': 'full',
                'tiering': [1],
            }
        }

        Use global settings if a pool has no individual settings.
        """
        # extraspecs default setting
        extraspecs_set = {
            'global_provisioning': 'full',
            'global_tiering': 'all',
        }

        provisioning_string = extraspecs.get(self.PROVISIONING_KEY, None)
        tiering_string = extraspecs.get(self.TIERING_SET_KEY, None)

        extraspecs_set = self._get_provisioning_setting(
            extraspecs_set, provisioning_string)

        extraspecs_set = self._get_tiering_setting(
            extraspecs_set, tiering_string)

        return extraspecs_set

    def _get_provisioning_setting(self, extraspecs_set, provisioning_string):
        # provisioning individual setting
        if provisioning_string and ':' in provisioning_string:
            provisioning_string = provisioning_string.replace(' ', '')
            provisioning_string = provisioning_string.split(';')

            for provisioning in provisioning_string:
                pool, value = provisioning.split(':', 1)

                if pool not in self.pool_list:
                    LOG.warning(_LW('Infortrend:provisioning '
                                    'this setting %(pool)s:%(value)s, '
                                    'pool [%(pool)s] not set in config.'), {
                                        'pool': pool,
                                        'value': value})
                else:
                    if pool not in extraspecs_set.keys():
                        extraspecs_set[pool] = {}

                    if value.lower() in self.PROVISIONING_VALUES:
                        extraspecs_set[pool]['provisioning'] = value.lower()
                    else:
                        extraspecs_set[pool]['provisioning'] = 'Err:%s' % value
                        LOG.warning(_LW('Infortrend:provisioning '
                                        'this setting %(pool)s:%(value)s, '
                                        '[%(value)s] is illegal'), {
                                            'pool': pool,
                                            'value': value})
        # provisioning global setting
        elif provisioning_string:
            provisioning = provisioning_string.replace(' ', '').lower()
            if provisioning in self.PROVISIONING_VALUES:
                extraspecs_set['global_provisioning'] = provisioning
            else:
                extraspecs_set['global_provisioning'] = 'Err:%s' % provisioning
                LOG.warning(_LW('Infortrend:provisioning '
                                '[%(value)s] is illegal'), {
                                    'value': provisioning_string})
        return extraspecs_set

    def _get_tiering_setting(self, extraspecs_set, tiering_string):
        # tiering individual setting
        if tiering_string and ':' in tiering_string:
            tiering_string = tiering_string.replace(' ', '')
            tiering_string = tiering_string.split(';')

            for tiering_set in tiering_string:
                pool, value = tiering_set.split(':', 1)

                if pool not in self.pool_list:
                    LOG.warning(_LW('Infortrend:tiering '
                                    'this setting %(pool)s:%(value)s, '
                                    'pool [%(pool)s] not set in config.'), {
                                        'pool': pool,
                                        'value': value})
                else:
                    if pool not in extraspecs_set.keys():
                        extraspecs_set[pool] = {}

                    if value.lower() == 'all':
                        extraspecs_set[pool]['tiering'] = 'all'
                    else:
                        value = value.split(',')
                        value = [int(i) for i in value]
                        value = list(set(value))

                        if value[-1] in range(4):
                            extraspecs_set[pool]['tiering'] = value
                        else:
                            extraspecs_set[pool]['tiering'] = 'Err:%s' % value
                            LOG.warning(_LW('Infortrend:tiering '
                                            'this setting %(pool)s:%(value)s, '
                                            '[%(err_value)s] is illegal'), {
                                                'pool': pool,
                                                'value': value,
                                                'err_value': value[-1]})
        # tiering global setting
        elif tiering_string:
            tiering_set = tiering_string.replace(' ', '').lower()

            if tiering_set != 'all':
                tiering_set = tiering_set.split(',')
                tiering_set = [int(i) for i in tiering_set]
                tiering_set = list(set(tiering_set))

                if tiering_set[-1] in range(4):
                    extraspecs_set['global_tiering'] = tiering_set
                else:
                    extraspecs_set['global_tiering'] = 'Err:%s' % tiering_set
                    LOG.warning(_LW('Infortrend:tiering '
                                    '[%(err_value)s] is illegal'), {
                                        'err_value': tiering_set[-1]})
        return extraspecs_set

    def _find_pool_id_by_name(self, pool_name):
        pool_id = None
        rc, lv_info = self._execute('ShowLV')
        for entry in lv_info:
            if entry['Name'] == pool_name:
                pool_id = entry['ID']
                break
        return pool_id

    def _get_system_id(self, system_ip):
        if not self.system_id:
            rc, device_info = self._execute('ShowDevice')
            for entry in device_info:
                if system_ip == entry['Connected-IP']:
                    self.system_id = str(int(entry['ID'], 16))
        return self.system_id

    @log_func
    def _get_lun_id(self, ch_id, controller='slot_a'):
        lun_id = -1

        if len(self.map_dict[controller][ch_id]) > 0:
            lun_id = self.map_dict[controller][ch_id][0]

        if lun_id == -1:
            msg = _('LUN number is out of bound '
                    'on channel id: %(ch_id)s.') % {'ch_id': ch_id}
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)
        else:
            return lun_id

    @log_func
    def _get_mapping_info(self, multipath):
        if multipath:
            return self._get_mapping_info_with_mpio()
        else:
            return self._get_mapping_info_with_normal()

    def _get_mapping_info_with_mpio(self):
        """Get all mapping channel id and minimun lun id mapping info.

        # R model with mcs
        map_chl = {
            'slot_a': ['2', '0']
            'slot_b': ['0', '3']
        }
        map_lun = ['0']

        # G model with mcs
        map_chl = {
            'slot_a': ['1', '2']
        }
        map_lun = ['0']

        :returns: all mapping channel id per slot and minimun lun id
        """
        map_chl = {
            'slot_a': []
        }
        if self._model_type == 'R':
            map_chl['slot_b'] = []

        # MPIO: Map all the channels specified in conf file
        # If MCS groups exist, only map to the minimum channel id per group
        for controller in map_chl.keys():
            for mcs in self.mcs_dict[controller]:
                map_mcs_chl = sorted((self.mcs_dict[controller][mcs]))[0]
                map_chl[controller].append(map_mcs_chl)

        map_lun = self._get_minimum_common_lun_id(map_chl)

        if not map_lun:
            msg = _('Cannot find a common lun id for mapping.')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        return map_chl, map_lun

    def _get_minimum_common_lun_id(self, channel_dict):
        """Find the minimun common lun id in all channels."""
        map_lun = []
        for lun_id in range(self.constants['MAX_LUN_MAP_PER_CHL']):
            has_mapped = False
            for controller in channel_dict.keys():
                for channel_id in channel_dict[controller]:
                    if lun_id not in self.map_dict[controller][channel_id]:
                        has_mapped = True
            if not has_mapped:
                map_lun.append(str(lun_id))
                break

        return map_lun

    @log_func
    def _get_mapping_info_with_normal(self):
        """Get the minimun mapping channel id and lun id mapping info.

        # G model and R model
        map_chl = {
            'slot_a': ['1']
        }
        map_lun = ['0']

        :returns: minimun mapping channel id per slot and lun id
        """
        map_chl = {
            'slot_a': []
        }
        map_lun = []

        ret_chl = self._get_minimun_mapping_channel_id('slot_a')
        lun_id = self._get_lun_id(ret_chl, 'slot_a')

        map_chl['slot_a'].append(ret_chl)
        map_lun.append(str(lun_id))

        return map_chl, map_lun

    @log_func
    def _get_minimun_mapping_channel_id(self, controller):
        empty_lun_num = 0
        min_map_chl = -1

        # Sort items to get a reliable behaviour. Dictionary items
        # are iterated in a random order because of hash randomization.
        # We don't care MCS group here, single path working as well.
        for mcs in sorted(self.mcs_dict[controller].keys()):
            mcs_chl = sorted((self.mcs_dict[controller][mcs]))[0]
            free_lun_num = len(self.map_dict[controller][mcs_chl])
            if empty_lun_num < free_lun_num:
                min_map_chl = mcs_chl
                empty_lun_num = free_lun_num

        if int(min_map_chl) < 0:
            msg = _('LUN map overflow on every channel.')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)
        else:
            return min_map_chl

    def _get_common_lun_map_id(self, wwpn_channel_info):
        map_lun = None

        for lun_id in range(self.constants['MAX_LUN_MAP_PER_CHL']):
            lun_id_exist = False
            for slot_name in ['slot_a', 'slot_b']:
                for wwpn in wwpn_channel_info:
                    channel_id = wwpn_channel_info[wwpn]['channel']
                    if channel_id not in self.map_dict[slot_name]:
                        continue
                    elif lun_id not in self.map_dict[slot_name][channel_id]:
                        lun_id_exist = True
            if not lun_id_exist:
                map_lun = str(lun_id)
                break
        return map_lun

    def _get_mcs_id(self, channel_id, controller):
        mcs_id = None

        for mcs in self.mcs_dict[controller]:
            if channel_id in self.mcs_dict[controller][mcs]:
                mcs_id = mcs
                break

        if mcs_id is None:
            msg = _('Cannot get mcs_id by channel id: %(channel_id)s.') % {
                'channel_id': channel_id}
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        return mcs_id

    def _concat_provider_location(self, model_dict):
        return '@'.join([i + '^' + str(model_dict[i]) for i in model_dict])

    def delete_volume(self, volume):
        """Delete the specific volume."""

        if not volume['provider_location']:
            LOG.warning(_LW('Volume %(volume_name)s '
                            'provider location not stored.'), {
                                'volume_name': volume['name']})
            return

        volume_id = volume['id'].replace('-', '')
        have_map = False

        part_id = self._extract_specific_provider_location(
            volume['provider_location'], 'partition_id')

        (check_exist, have_map, part_id) = (
            self._check_volume_exist(volume_id, part_id)
        )

        if not check_exist:
            LOG.warning(_LW('Volume %(volume_id)s already deleted.'), {
                'volume_id': volume_id})
            return

        if have_map:
            self._execute('DeleteMap', 'part', part_id, '-y')

        self._execute('DeletePartition', part_id, '-y')

        LOG.info(_LI('Delete Volume %(volume_id)s completed.'), {
            'volume_id': volume_id})

    def _check_replica_completed(self, replica):
        if ((replica['Type'] == 'Copy' and replica['Status'] == 'Completed') or
                (replica['Type'] == 'Mirror' and
                    replica['Status'] == 'Mirror')):
            return True
        # show the progress percentage
        status = replica['Progress'].lower()
        LOG.info(_LI('Replica from %(source_type)s: [%(source_name)s] '
                     'progess [%(progess)s].'), {
                         'source_type': replica['Source-Type'],
                         'source_name': replica['Source-Name'],
                         'progess': status})
        return False

    def _check_volume_exist(self, volume_id, part_id):
        check_exist = False
        have_map = False
        result_part_id = part_id

        rc, part_list = self._execute('ShowPartition', '-l')

        for entry in part_list:
            if entry['Name'] == volume_id:
                check_exist = True

                if part_id is None:
                    result_part_id = entry['ID']
                if entry['Mapped'] == 'true':
                    have_map = True

        if check_exist:
            return (check_exist, have_map, result_part_id)
        else:
            return (False, False, None)

    def create_cloned_volume(self, volume, src_vref):
        """Create a clone of the volume by volume copy."""

        volume_id = volume['id'].replace('-', '')
        #  Step1 create a snapshot of the volume
        src_part_id = self._extract_specific_provider_location(
            src_vref['provider_location'], 'partition_id')

        if src_part_id is None:
            src_part_id = self._get_part_id(volume_id)

        model_update = self._create_volume_from_volume(volume, src_part_id)

        LOG.info(_LI('Create Cloned Volume %(volume_id)s completed.'), {
            'volume_id': volume['id']})
        return model_update

    def _create_volume_from_volume(self, dst_volume, src_part_id):
        # create the target volume for volume copy
        dst_volume_id = dst_volume['id'].replace('-', '')

        self._create_partition_by_default(dst_volume)

        dst_part_id = self._get_part_id(dst_volume_id)
        # prepare return value
        system_id = self._get_system_id(self.ip)
        model_dict = {
            'system_id': system_id,
            'partition_id': dst_part_id,
        }

        model_info = self._concat_provider_location(model_dict)
        model_update = {"provider_location": model_info}

        # clone the volume from the origin partition
        commands = (
            'Cinder-Cloned', 'part', src_part_id, 'part', dst_part_id
        )
        self._execute('CreateReplica', *commands)
        self._wait_replica_complete(dst_part_id)

        return model_update

    def _extract_specific_provider_location(self, provider_location, key):
        if not provider_location:
            msg = _('Failed to get provider location.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        provider_location_dict = self._extract_all_provider_location(
            provider_location)

        result = provider_location_dict.get(key, None)
        return result

    @log_func
    def _extract_all_provider_location(self, provider_location):
        provider_location_dict = {}
        dict_entry = provider_location.split("@")
        for entry in dict_entry:
            key, value = entry.split('^', 1)
            if value == 'None':
                value = None
            provider_location_dict[key] = value

        return provider_location_dict

    def create_export(self, context, volume):
        model_update = volume['provider_location']

        LOG.info(_LI('Create export done from Volume %(volume_id)s.'), {
            'volume_id': volume['id']})

        return {'provider_location': model_update}

    def get_volume_stats(self, refresh=False):
        """Get volume status.

        If refresh is True, update the status first.
        """
        if self._volume_stats is None or refresh:
            self._update_volume_stats()

        LOG.info(_LI(
            'Successfully update volume stats. '
            'backend: %(volume_backend_name)s, '
            'vendor: %(vendor_name)s, '
            'model_type: %(model_type)s, '
            'system_id: %(system_id)s, '
            'status: %(status)s, '
            'driver_version: %(driver_version)s, '
            'storage_protocol: %(storage_protocol)s.'), self._volume_stats)

        return self._volume_stats

    def _update_volume_stats(self):

        self.backend_name = self.configuration.safe_get('volume_backend_name')

        data = {
            'volume_backend_name': self.backend_name,
            'vendor_name': 'Infortrend',
            'driver_version': self.VERSION,
            'storage_protocol': self.protocol,
            'model_type': self._model_type,
            'system_id': self._get_system_id(self.ip),
            'status': self._check_connection(),
            'pools': self._update_pools_stats(),
        }
        self._volume_stats = data

    def _check_connection(self):
        rc, out = self._execute('CheckConnection')
        if rc == 0:
            return 'Connected'
        elif rc in (9, 13):
            self._init_raid_connection()
            self._set_raidcmd()
            return 'Reconnected'
        else:
            return 'Error: %s' % out

    def _update_pools_stats(self):
        self._update_pool_tiers()
        enable_specs_dict = self._get_enable_specs_on_array()

        if 'Thin Provisioning' in enable_specs_dict.keys():
            provisioning_support = True
        else:
            provisioning_support = False

        rc, pools_info = self._execute('ShowLV')
        pools = []
        system_id = self._get_system_id(self.ip)

        if provisioning_support:
            rc, part_list = self._execute('ShowPartition', '-l')

        for pool in pools_info:
            if pool['Name'] in self.pool_list:
                total_space = float(pool['Size'].split(' ', 1)[0])
                available_space = float(pool['Available'].split(' ', 1)[0])

                total_capacity_gb = round(mi_to_gi(total_space), 2)
                free_capacity_gb = round(mi_to_gi(available_space), 2)

                _pool = {
                    'pool_name': pool['Name'],
                    'pool_id': pool['ID'],
                    'location_info': 'Infortrend:%s' % system_id,
                    'total_capacity_gb': total_capacity_gb,
                    'free_capacity_gb': free_capacity_gb,
                    'reserved_percentage': 0,
                    'QoS_support': False,
                    'thick_provisioning_support': True,
                    'thin_provisioning_support': provisioning_support,
                }

                if provisioning_support:
                    provisioning_factor = self.configuration.safe_get(
                        'max_over_subscription_ratio')
                    provisioned_space = self._get_provisioned_space(
                        pool['ID'], part_list)
                    provisioned_capacity_gb = round(
                        mi_to_gi(provisioned_space), 2)
                    _pool['provisioned_capacity_gb'] = provisioned_capacity_gb
                    _pool['max_over_subscription_ratio'] = provisioning_factor

                pools.append(_pool)

        return pools

    def _get_provisioned_space(self, pool_id, part_list):
        provisioning_space = 0
        for entry in part_list:
            if entry['LV-ID'] == pool_id:
                provisioning_space += int(entry['Size'])
        return provisioning_space

    def _update_pool_tiers(self):
        """Setup the tier pools information.

        tier_pools_dict = {
            '12345678': [0, 1, 2, 3], # Pool 12345678 has 4 tiers: 0, 1, 2, 3
            '87654321': [0, 1, 3],    # Pool 87654321 has 3 tiers: 0, 1, 3
        }
        """
        rc, lv_info = self._execute('ShowLV', 'tier')

        temp_dict = {}
        for entry in lv_info:
            if entry['LV-Name'] in self.pool_list:
                if entry['LV-ID'] not in temp_dict.keys():
                    temp_dict[entry['LV-ID']] = []
                temp_dict[entry['LV-ID']].append(int(entry['Tier']))

        self.tier_pools_dict = temp_dict

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""

        snapshot_id = snapshot['id'].replace('-', '')
        volume_id = snapshot['volume_id'].replace('-', '')

        LOG.debug('Create Snapshot %(snapshot)s volume %(volume)s.',
                  {'snapshot': snapshot_id, 'volume': volume_id})

        model_update = {}
        part_id = self._get_part_id(volume_id)

        if part_id is None:
            msg = _('Failed to get Partition ID for volume %(volume_id)s.') % {
                'volume_id': volume_id}
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        @lockutils.synchronized(
            'snapshot-' + part_id, 'infortrend-', True)
        def do_create_snapshot():
            self._execute('CreateSnapshot', 'part', part_id)
            rc, tmp_snapshot_list = self._execute(
                'ShowSnapshot', 'part=%s' % part_id)
            return tmp_snapshot_list

        snapshot_list = do_create_snapshot()

        LOG.info(_LI(
            'Create success. '
            'Snapshot: %(snapshot)s, '
            'Snapshot ID in raid: %(raid_snapshot_id)s, '
            'volume: %(volume)s.'), {
                'snapshot': snapshot_id,
                'raid_snapshot_id': snapshot_list[-1]['SI-ID'],
                'volume': volume_id})
        model_update['provider_location'] = snapshot_list[-1]['SI-ID']
        return model_update

    def delete_snapshot(self, snapshot):
        """Delete the snapshot."""

        snapshot_id = snapshot['id'].replace('-', '')
        volume_id = snapshot['volume_id'].replace('-', '')

        LOG.debug('Delete Snapshot %(snapshot)s volume %(volume)s.',
                  {'snapshot': snapshot_id, 'volume': volume_id})

        raid_snapshot_id = self._get_raid_snapshot_id(snapshot)

        if raid_snapshot_id:

            self._execute('DeleteSnapshot', raid_snapshot_id, '-y')

            LOG.info(_LI('Delete Snapshot %(snapshot_id)s completed.'), {
                'snapshot_id': snapshot_id})
        else:
            LOG.warning(_LW('Snapshot %(snapshot_id)s '
                            'provider_location not stored.'), {
                                'snapshot_id': snapshot['id']})

    def _get_raid_snapshot_id(self, snapshot):
        if 'provider_location' in snapshot:
            return snapshot['provider_location']
        return

    def _get_part_id(self, volume_id, pool_id=None, part_list=None):
        if part_list is None:
            rc, part_list = self._execute('ShowPartition')
        for entry in part_list:
            if pool_id is None:
                if entry['Name'] == volume_id:
                    return entry['ID']
            else:
                if entry['Name'] == volume_id and entry['LV-ID'] == pool_id:
                    return entry['ID']
        return

    def create_volume_from_snapshot(self, volume, snapshot):
        raid_snapshot_id = self._get_raid_snapshot_id(snapshot)

        if raid_snapshot_id is None:
            msg = _('Failed to get Raid Snapshot ID '
                    'from snapshot: %(snapshot_id)s.') % {
                        'snapshot_id': snapshot['id']}
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        src_part_id = self._check_snapshot_filled_block(raid_snapshot_id)

        model_update = self._create_volume_from_snapshot_id(
            volume, raid_snapshot_id, src_part_id)

        LOG.info(_LI(
            'Create Volume %(volume_id)s from '
            'snapshot %(snapshot_id)s completed.'), {
                'volume_id': volume['id'],
                'snapshot_id': snapshot['id']})

        return model_update

    def _check_snapshot_filled_block(self, raid_snapshot_id):
        rc, snapshot_list = self._execute(
            'ShowSnapshot', 'si=%s' % raid_snapshot_id, '-l')

        if snapshot_list and snapshot_list[0]['Total-filled-block'] == '0':
            return snapshot_list[0]['Partition-ID']
        return

    def _create_volume_from_snapshot_id(
            self, dst_volume, raid_snapshot_id, src_part_id):
        # create the target volume for volume copy
        dst_volume_id = dst_volume['id'].replace('-', '')

        self._create_partition_by_default(dst_volume)

        dst_part_id = self._get_part_id(dst_volume_id)
        # prepare return value
        system_id = self._get_system_id(self.ip)
        model_dict = {
            'system_id': system_id,
            'partition_id': dst_part_id,
        }

        model_info = self._concat_provider_location(model_dict)
        model_update = {"provider_location": model_info}

        if src_part_id:
            # clone the volume from the origin partition
            commands = (
                'Cinder-Snapshot', 'part', src_part_id, 'part', dst_part_id
            )
            self._execute('CreateReplica', *commands)
            self._wait_replica_complete(dst_part_id)

        # clone the volume from the snapshot
        commands = (
            'Cinder-Snapshot', 'si', raid_snapshot_id, 'part', dst_part_id
        )
        self._execute('CreateReplica', *commands)
        self._wait_replica_complete(dst_part_id)

        return model_update

    def initialize_connection(self, volume, connector):
        system_id = self._get_system_id(self.ip)
        LOG.debug('Connector_info: %s' % connector)

        @lockutils.synchronized(
            '%s-connection' % system_id, 'infortrend-', True)
        def lock_initialize_conn():
            if self.protocol == 'iSCSI':
                multipath = connector.get('multipath', False)
                return self._initialize_connection_iscsi(
                    volume, connector, multipath)
            elif self.protocol == 'FC':
                return self._initialize_connection_fc(
                    volume, connector)
            else:
                msg = _('Unknown protocol: %(protocol)s.') % {
                    'protocol': self.protocol}
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)

        return lock_initialize_conn()

    def _initialize_connection_fc(self, volume, connector):
        self._init_map_info()
        self._update_map_info(True)

        map_lun, target_wwpns, initiator_target_map = (
            self._do_fc_connection(volume, connector)
        )

        properties = self._generate_fc_connection_properties(
            map_lun, target_wwpns, initiator_target_map)

        LOG.info(_LI('Successfully initialized connection. '
                     'target_wwn: %(target_wwn)s, '
                     'initiator_target_map: %(initiator_target_map)s, '
                     'lun: %(target_lun)s.'), properties['data'])
        return properties

    @log_func
    def _do_fc_connection(self, volume, connector):
        volume_id = volume['id'].replace('-', '')
        target_wwpns = []

        partition_data = self._extract_all_provider_location(
            volume['provider_location'])
        part_id = partition_data['partition_id']

        if part_id is None:
            part_id = self._get_part_id(volume_id)

        wwpn_list, wwpn_channel_info = self._get_wwpn_list()

        initiator_target_map, target_wwpns = self._build_initiator_target_map(
            connector, wwpn_list)

        map_lun = self._get_common_lun_map_id(wwpn_channel_info)
        rc, part_mapping = self._execute('ShowMap', 'part=%s' % part_id)

        create_new_maps = False
        map_lun_list = []

        # We need to check all the maps first
        # Because fibre needs a consistent lun id
        for initiator_wwpn in sorted(initiator_target_map):
            for target_wwpn in initiator_target_map[initiator_wwpn]:
                ch_id = wwpn_channel_info[target_wwpn.upper()]['channel']
                controller = wwpn_channel_info[target_wwpn.upper()]['slot']
                target_id = self.target_dict[controller][ch_id]

                exist_lun_id = self._check_map(
                    ch_id, target_id, part_mapping, initiator_wwpn)
                map_lun_list.append(exist_lun_id)

        # To check if all the luns are the same
        if map_lun_list.count(map_lun_list[0]) == len(map_lun_list):
            if map_lun_list[0] == -1:
                create_new_maps = True
            else:
                map_lun = str(map_lun_list[0])
        else:
            create_new_maps = True

        LOG.info(_LI('volume: [%(volume)s], '
                     'mapped_lun_list: %(list)s, '
                     'create_new_maps: [%(flag)s]'), {
                         'volume': volume['id'],
                         'list': map_lun_list,
                         'flag': create_new_maps})

        if create_new_maps:
            for initiator_wwpn in sorted(initiator_target_map):
                for target_wwpn in initiator_target_map[initiator_wwpn]:
                    ch_id = wwpn_channel_info[target_wwpn.upper()]['channel']
                    controller = wwpn_channel_info[target_wwpn.upper()]['slot']
                    target_id = self.target_dict[controller][ch_id]
                    host_filter = self._create_host_filter(initiator_wwpn)
                    commands = (
                        'part', part_id, ch_id, target_id, map_lun,
                        host_filter
                    )
                    rc, out = self._execute('CreateMap', *commands)
                    if rc != 0:
                        msg = _('Volume[%(part_id)s] create map failed, '
                                'Ch:[%(Ch)s] ID:[%(tid)s] LUN:[%(lun)s].') % {
                                    'part_id': part_id, 'Ch': ch_id,
                                    'tid': target_id, 'lun': map_lun}
                        LOG.error(msg)
                        raise exception.VolumeDriverException(message=msg)

                    if int(map_lun) in self.map_dict[controller][ch_id]:
                        self.map_dict[controller][ch_id].remove(int(map_lun))

        return map_lun, target_wwpns, initiator_target_map

    def _build_initiator_target_map(self, connector, all_target_wwpns):
        initiator_target_map = {}
        target_wwpns = []

        if self.fc_lookup_service:
            lookup_map = (
                self.fc_lookup_service.get_device_mapping_from_network(
                    connector['wwpns'], all_target_wwpns)
            )
            for fabric_name in lookup_map:
                fabric = lookup_map[fabric_name]
                target_wwpns.extend(fabric['target_port_wwn_list'])
                for initiator in fabric['initiator_port_wwn_list']:
                    initiator_target_map[initiator] = (
                        fabric['target_port_wwn_list']
                    )
        else:
            initiator_wwns = connector['wwpns']
            target_wwpns = all_target_wwpns
            for initiator in initiator_wwns:
                initiator_target_map[initiator] = all_target_wwpns

        return initiator_target_map, target_wwpns

    def _generate_fc_connection_properties(
            self, lun_id, target_wwpns, initiator_target_map):

        return {
            'driver_volume_type': 'fibre_channel',
            'data': {
                'target_discovered': True,
                'target_lun': int(lun_id),
                'target_wwn': target_wwpns,
                'initiator_target_map': initiator_target_map,
            },
        }

    @log_func
    def _initialize_connection_iscsi(self, volume, connector, multipath):
        self._init_map_info()
        self._update_map_info(multipath)

        volume_id = volume['id'].replace('-', '')

        partition_data = self._extract_all_provider_location(
            volume['provider_location'])  # system_id, part_id

        system_id = partition_data['system_id']
        part_id = partition_data['partition_id']
        if part_id is None:
            part_id = self._get_part_id(volume_id)

        self._set_host_iqn(connector['initiator'])

        map_chl, map_lun = self._get_mapping_info(multipath)

        lun_id = map_lun[0]

        iqns, ips, luns = self._iscsi_create_map(
            part_id, map_chl, lun_id, connector['initiator'], system_id)

        properties = self._generate_iscsi_connection_properties(
            iqns, ips, luns, volume, multipath)
        LOG.info(_LI('Successfully initialized connection '
                     'with volume: %(volume_id)s.'), properties['data'])
        return properties

    def _set_host_iqn(self, host_iqn):

        rc, iqn_list = self._execute('ShowIQN')

        check_iqn_exist = False
        for entry in iqn_list:
            if entry['IQN'] == host_iqn:
                check_iqn_exist = True

        if not check_iqn_exist:
            self._execute(
                'CreateIQN', host_iqn, self._truncate_host_name(host_iqn))

    def _truncate_host_name(self, iqn):
        if len(iqn) > 16:
            return iqn[-16:]
        else:
            return iqn

    @log_func
    def _generate_iqn(self, channel_info):
        slot_id = 1 if channel_info['controller'] == 'slot_a' else 2
        return self.iqn % (
            channel_info['system_id'],
            channel_info['mcs_id'],
            channel_info['target_id'],
            slot_id)

    @log_func
    def _get_ip_by_channel(
            self, channel_id, net_list, controller='slot_a'):

        slot_name = 'slotA' if controller == 'slot_a' else 'slotB'

        for entry in net_list:
            if entry['ID'] == channel_id and entry['Slot'] == slot_name:
                if entry['IPv4'] == '0.0.0.0':
                    msg = _(
                        'Please set ip on Channel[%(channel_id)s] '
                        'with controller[%(controller)s].') % {
                            'channel_id': channel_id, 'controller': slot_name}
                    LOG.error(msg)
                    raise exception.VolumeDriverException(message=msg)
                else:
                    return entry['IPv4']

        msg = _(
            'Can not find channel[%(channel_id)s] '
            'with controller[%(controller)s].') % {
                'channel_id': channel_id, 'controller': slot_name}
        LOG.error(msg)
        raise exception.VolumeDriverException(message=msg)
        return

    def _get_wwpn_list(self):
        rc, wwn_list = self._execute('ShowWWN')

        wwpn_list = []
        wwpn_channel_info = {}

        for entry in wwn_list:
            channel_id = entry['CH']
            if 'BID' in entry['ID']:
                slot_name = 'slot_b'
            else:
                slot_name = 'slot_a'

            if channel_id in self.map_dict[slot_name]:
                wwpn_list.append(entry['WWPN'])

                wwpn_channel_info[entry['WWPN']] = {
                    'channel': channel_id,
                    'slot': slot_name,
                }

        return wwpn_list, wwpn_channel_info

    @log_func
    def _generate_iscsi_connection_properties(
            self, iqns, ips, luns, volume, multipath):

        portals = []

        for i in range(len(ips)):
            discovery_ip = '%s:%s' % (
                ips[i], self.constants['ISCSI_PORT'])
            discovery_iqn = iqns[i]
            portals.append(discovery_ip)

            if not self._do_iscsi_discovery(discovery_iqn, discovery_ip):
                msg = _(
                    'Could not find iSCSI target '
                    'for volume: [%(volume_id)s] '
                    'portal: [%(discovery_ip)s] '
                    'iqn: [%(discovery_iqn)s]'
                    'for path: [%(i)s/%(len)s]') % {
                        'volume_id': volume['id'],
                        'discovery_ip': discovery_ip,
                        'discovery_iqn': discovery_iqn,
                        'i': i + 1, 'len': len(ips)}
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)

        properties = {
            'target_discovered': True,
            'target_iqn': iqns[0],
            'target_portal': portals[0],
            'target_lun': luns[0],
            'volume_id': volume['id'],
        }

        if multipath:
            properties['target_iqns'] = iqns
            properties['target_portals'] = portals
            properties['target_luns'] = luns

        if 'provider_auth' in volume:
            auth = volume['provider_auth']
            if auth:
                (auth_method, auth_username, auth_secret) = auth.split()
                properties['auth_method'] = auth_method
                properties['auth_username'] = auth_username
                properties['auth_password'] = auth_secret

        return {
            'driver_volume_type': 'iscsi',
            'data': properties,
        }

    @log_func
    def _do_iscsi_discovery(self, target_iqn, target_ip):
        rc, out = self._execute(
            'ExecuteCommand',
            'iscsiadm', '-m', 'discovery',
            '-t', 'sendtargets', '-p',
            target_ip,
            run_as_root=True)

        if rc != 0:
            LOG.error(_LE(
                'Can not discovery in %(target_ip)s with %(target_iqn)s.'), {
                    'target_ip': target_ip, 'target_iqn': target_iqn})
            return False
        else:
            for target in out.splitlines():
                if target_iqn in target and target_ip in target:
                    return True
        return False

    def extend_volume(self, volume, new_size):
        volume_id = volume['id'].replace('-', '')

        part_id = self._extract_specific_provider_location(
            volume['provider_location'], 'partition_id')

        if part_id is None:
            part_id = self._get_part_id(volume_id)

        expand_size = new_size - volume['size']

        if '.' in ('%s' % expand_size):
            expand_size = round(gi_to_mi(float(expand_size)))
            expand_command = 'size=%sMB' % expand_size
        else:
            expand_command = 'size=%sGB' % expand_size

        self._execute('SetPartition', 'expand', part_id, expand_command)

        LOG.info(_LI(
            'Successfully extended volume %(volume_id)s to size %(size)s.'), {
                'volume_id': volume['id'], 'size': new_size})

    def terminate_connection(self, volume, connector):
        system_id = self._get_system_id(self.ip)

        @lockutils.synchronized(
            '%s-connection' % system_id, 'infortrend-', True)
        def lock_terminate_conn():
            volume_id = volume['id'].replace('-', '')
            conn_info = None

            part_id = self._extract_specific_provider_location(
                volume['provider_location'], 'partition_id')

            if part_id is None:
                part_id = self._get_part_id(volume_id)

            self._delete_map(part_id, connector)

            if self.protocol == 'iSCSI':
                lun_map_exist = self._check_initiator_has_lun_map(
                    connector['initiator'])
                if not lun_map_exist:
                    host_name = self._truncate_host_name(
                        connector['initiator'])
                    self._execute('DeleteIQN', host_name)

            elif self.protocol == 'FC':
                conn_info = {'driver_volume_type': 'fibre_channel',
                             'data': {}}

                lun_map_exist = self._check_initiator_has_lun_map(
                    connector['wwpns'])
                if not lun_map_exist:
                    wwpn_list, wwpn_channel_info = self._get_wwpn_list()
                    init_target_map, target_wwpns = (
                        self._build_initiator_target_map(connector, wwpn_list)
                    )
                    conn_info['data']['initiator_target_map'] = init_target_map

            LOG.info(_LI(
                'Successfully terminated connection '
                'for volume: %(volume_id)s.'), {
                    'volume_id': volume['id']})

            return conn_info
        return lock_terminate_conn()

    def _delete_map(self, part_id, connector):
        rc, part_map_info = self._execute('ShowMap', 'part=%s' % part_id)
        if self.protocol == 'iSCSI':
            host = connector['initiator'].lower()
            host = (host,)
        elif self.protocol == 'FC':
            host = [x.lower() for x in connector['wwpns']]

        temp_ch = None
        temp_tid = None
        temp_lun = None

        # The default result of ShowMap is ordered by Ch-Target-LUN
        # The same lun-map might have different host filters
        # We need to specify Ch-Target-LUN and delete it only once
        if len(part_map_info) > 0:
            for entry in part_map_info:
                if entry['Host-ID'].lower() in host:
                    if not (entry['Ch'] == temp_ch and
                            entry['Target'] == temp_tid and
                            entry['LUN'] == temp_lun):
                        self._execute(
                            'DeleteMap', 'part', part_id, entry['Ch'],
                            entry['Target'], entry['LUN'], '-y')
                        temp_ch = entry['Ch']
                        temp_tid = entry['Target']
                        temp_lun = entry['LUN']
        return

    def migrate_volume(self, volume, host, new_extraspecs=None):
        is_valid, dst_pool_id = (
            self._is_valid_for_storage_assisted_migration(host, volume)
        )
        if not is_valid:
            return (False, None)

        src_pool_id = self._get_volume_pool_id(volume)

        if src_pool_id != dst_pool_id:

            model_dict = self._migrate_volume_with_pool(
                volume, dst_pool_id, new_extraspecs)

            model_update = {
                "provider_location":
                    self._concat_provider_location(model_dict),
            }

            LOG.info(_LI('Migrate Volume %(volume_id)s completed.'), {
                'volume_id': volume['id']})
        else:
            model_update = {
                "provider_location": volume['provider_location'],
            }

        return (True, model_update)

    def _is_valid_for_storage_assisted_migration(self, host, volume):

        if 'location_info' not in host['capabilities']:
            LOG.error(_LE('location_info not stored in pool.'))
            return (False, None)

        vendor = host['capabilities']['location_info'].split(':')[0]
        dst_system_id = host['capabilities']['location_info'].split(':')[-1]

        if vendor != 'Infortrend':
            LOG.error(_LE('Vendor should be Infortrend for migration.'))
            return (False, None)

        # It should be the same raid for migration
        src_system_id = self._get_system_id(self.ip)
        if dst_system_id != src_system_id:
            LOG.error(_LE('Migration must be performed '
                          'on the same Infortrend array.'))
            return (False, None)

        # We don't support volume live migration
        if volume['status'].lower() != 'available':
            LOG.error(_LE('Volume status must be available for migration.'))
            return (False, None)

        if 'pool_id' not in host['capabilities']:
            LOG.error(_LE('Failed to get target pool id.'))
            return (False, None)

        dst_pool_id = host['capabilities']['pool_id']
        if dst_pool_id is None:
            return (False, None)

        return (True, dst_pool_id)

    def _migrate_volume_with_pool(self, volume, dst_pool_id, extraspecs=None):
        volume_id = volume['id'].replace('-', '')

        # Get old partition data for delete map
        partition_data = self._extract_all_provider_location(
            volume['provider_location'])

        src_part_id = partition_data['partition_id']

        if src_part_id is None:
            src_part_id = self._get_part_id(volume_id)

        # Create New Partition
        self._create_partition_with_pool(volume, dst_pool_id, extraspecs)

        dst_part_id = self._get_part_id(
            volume_id, pool_id=dst_pool_id)

        if dst_part_id is None:
            msg = _('Failed to get new part id in new pool: %(pool_id)s.') % {
                'pool_id': dst_pool_id}
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        # Volume Mirror from old partition into new partition
        commands = (
            'Cinder-Migrate', 'part', src_part_id, 'part', dst_part_id,
            'type=mirror'
        )
        self._execute('CreateReplica', *commands)

        self._wait_replica_complete(dst_part_id)

        self._execute('DeleteMap', 'part', src_part_id, '-y')
        self._execute('DeletePartition', src_part_id, '-y')

        model_dict = {
            'system_id': partition_data['system_id'],
            'partition_id': dst_part_id,
        }

        return model_dict

    def update_migrated_volume(self, ctxt, volume, new_volume,
                               original_volume_status):
        """Return model update for migrated volume."""

        src_volume_id = volume['id'].replace('-', '')
        dst_volume_id = new_volume['id'].replace('-', '')
        part_id = self._extract_specific_provider_location(
            new_volume['provider_location'], 'partition_id')

        if part_id is None:
            part_id = self._get_part_id(dst_volume_id)

        LOG.debug(
            'Rename partition %(part_id)s '
            'into new volume %(new_volume)s.', {
                'part_id': part_id, 'new_volume': dst_volume_id})
        try:
            self._execute('SetPartition', part_id, 'name=%s' % src_volume_id)
        except exception.InfortrendCliException:
            LOG.exception(_LE('Failed to rename %(new_volume)s into '
                              '%(volume)s.'), {'new_volume': new_volume['id'],
                                               'volume': volume['id']})
            return {'_name_id': new_volume['_name_id'] or new_volume['id']}

        LOG.info(_LI('Update migrated volume %(new_volume)s completed.'), {
            'new_volume': new_volume['id']})

        model_update = {
            '_name_id': None,
            'provider_location': new_volume['provider_location'],
        }
        return model_update

    def _wait_replica_complete(self, part_id):
        start_time = int(time.time())
        timeout = self._replica_timeout

        def _inner():
            check_done = False
            try:
                rc, replica_list = self._execute('ShowReplica', '-l')
                for entry in replica_list:
                    if (entry['Target'] == part_id and
                            self._check_replica_completed(entry)):
                        check_done = True
                        self._execute('DeleteReplica', entry['Pair-ID'], '-y')
            except Exception:
                check_done = False
                LOG.exception(_LE('Cannot detect replica status.'))

            if check_done:
                raise loopingcall.LoopingCallDone()

            if int(time.time()) - start_time > timeout:
                msg = _('Wait replica complete timeout.')
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)

        timer = loopingcall.FixedIntervalLoopingCall(_inner)
        timer.start(interval=15).wait()

    def _get_enable_specs_on_array(self):
        enable_specs = {}
        rc, license_list = self._execute('ShowLicense')

        for key, value in license_list.items():
            if value['Support']:
                enable_specs[key] = value

        return enable_specs

    def manage_existing_get_size(self, volume, ref):
        """Return size of volume to be managed by manage_existing."""

        volume_data = self._get_existing_volume_ref_data(ref)
        volume_pool_id = self._get_volume_pool_id(volume)

        if not volume_data:
            msg = _('Specified volume does not exist.')
            LOG.error(msg)
            raise exception.ManageExistingInvalidReference(
                existing_ref=ref, reason=msg)

        if volume_data['Mapped'].lower() != 'false':
            msg = _('The specified volume is mapped. '
                    'Please unmap first for Openstack using.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        if volume_data['LV-ID'] != volume_pool_id:
            msg = _('The specified volume pool is wrong.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        return int(math.ceil(mi_to_gi(float(volume_data['Size']))))

    def manage_existing(self, volume, ref):
        volume_id = volume['id'].replace('-', '')

        volume_data = self._get_existing_volume_ref_data(ref)

        if not volume_data:
            msg = _('Specified logical volume does not exist.')
            LOG.error(msg)
            raise exception.ManageExistingInvalidReference(
                existing_ref=ref, reason=msg)

        self._execute('SetPartition', volume_data['ID'], 'name=%s' % volume_id)

        model_dict = {
            'system_id': self._get_system_id(self.ip),
            'partition_id': volume_data['ID'],
        }
        model_update = {
            "provider_location": self._concat_provider_location(model_dict),
        }

        LOG.info(_LI('Rename Volume %(volume_id)s completed.'), {
            'volume_id': volume['id']})

        return model_update

    def _get_existing_volume_ref_data(self, ref):

        if 'source-name' in ref:
            key = 'Name'
            find_key = ref['source-name']
        elif 'source-id' in ref:
            key = 'ID'
            find_key = ref['source-id']
        else:
            msg = _('Reference must contain source-id or source-name.')
            LOG.error(msg)
            raise exception.ManageExistingInvalidReference(
                existing_ref=ref, reason=msg)

        ref_dict = {}
        rc, part_list = self._execute('ShowPartition', '-l')

        for entry in part_list:
            if entry[key] == find_key:
                ref_dict = entry
                break

        return ref_dict

    def unmanage(self, volume):
        volume_id = volume['id'].replace('-', '')
        part_id = self._extract_specific_provider_location(
            volume['provider_location'], 'partition_id')

        if part_id is None:
            part_id = self._get_part_id(volume_id)

        new_vol_name = self._get_unmanaged_volume_name(volume_id)
        self._execute('SetPartition', part_id, 'name=%s' % new_vol_name)

        LOG.info(_LI('Unmanage volume %(volume_id)s completed.'), {
            'volume_id': volume_id})

    def _get_unmanaged_volume_name(self, volume_id):
        return self.unmanaged_prefix % volume_id[:-17]

    def _check_volume_attachment(self, volume):
        if not volume['volume_attachment']:
            return False
        return True

    def _check_volume_has_snapshot(self, volume):
        part_id = self._extract_specific_provider_location(
            volume['provider_location'], 'partition_id')

        rc, snapshot_list = self._execute('ShowSnapshot', 'part=%s' % part_id)

        if len(snapshot_list) > 0:
            return True
        return False

    def retype(self, ctxt, volume, new_type, diff, host):
        """Convert the volume to the new volume type."""
        src_pool_name = volume['host'].split('#')[-1]
        dst_pool_name = host['host'].split('#')[-1]

        if src_pool_name != dst_pool_name:
            if self._check_volume_attachment(volume):
                LOG.error(_LE(
                    'Volume %(volume_id)s cannot be retyped '
                    'during attachment.'), {
                        'volume_id': volume['id']})
                return False

            if self._check_volume_has_snapshot(volume):
                LOG.error(_LE(
                    'Volume %(volume_id)s cannot be retyped '
                    'because it has snapshot.'), {
                        'volume_id': volume['id']})
                return False

            new_extraspecs = new_type['extra_specs']
            rc, model_update = self.migrate_volume(
                volume, host, new_extraspecs)

            if rc:
                LOG.info(_LI(
                    'Retype Volume %(volume_id)s is done '
                    'and migrated to pool %(pool_id)s.'), {
                        'volume_id': volume['id'],
                        'pool_id': host['capabilities']['pool_id']})

            return (rc, model_update)
        else:
            # extract extraspecs for pool
            src_extraspec = new_type['extra_specs'].copy()

            if self.PROVISIONING_KEY in diff['extra_specs']:
                src_prov = diff['extra_specs'][self.PROVISIONING_KEY][0]
                src_extraspec[self.PROVISIONING_KEY] = src_prov

            if self.TIERING_SET_KEY in diff['extra_specs']:
                src_tier = diff['extra_specs'][self.TIERING_SET_KEY][0]
                src_extraspec[self.TIERING_SET_KEY] = src_tier

            if src_extraspec != new_type['extra_specs']:
                src_extraspec_set = self._get_extraspecs_set(
                    src_extraspec)
                new_extraspec_set = self._get_extraspecs_set(
                    new_type['extra_specs'])

                src_extraspecs = self._get_pool_extraspecs(
                    src_pool_name, src_extraspec_set)
                new_extraspecs = self._get_pool_extraspecs(
                    dst_pool_name, new_extraspec_set)

                if not self._check_volume_type_diff(
                        src_extraspecs, new_extraspecs, 'provisioning'):
                    LOG.warning(_LW(
                        'The provisioning: [%(src)s] to [%(new)s] '
                        'is unable to retype.'), {
                            'src': src_extraspecs['provisioning'],
                            'new': new_extraspecs['provisioning']})
                    return False

                elif not self._check_volume_type_diff(
                        src_extraspecs, new_extraspecs, 'tiering'):
                    self._execute_retype_tiering(new_extraspecs, volume)

            LOG.info(_LI('Retype Volume %(volume_id)s is completed.'), {
                'volume_id': volume['id']})

            return True

    def _check_volume_type_diff(self, src_extraspecs, new_extraspecs, key):
        if src_extraspecs[key] != new_extraspecs[key]:
            return False
        return True

    def _execute_retype_tiering(self, new_pool_extraspecs, volume):
        part_id = self._extract_specific_provider_location(
            volume['provider_location'], 'partition_id')

        if part_id is None:
            volume_id = volume['id'].replace('-', '')
            part_id = self._get_part_id(volume_id)

        pool_name = volume['host'].split('#')[-1]
        pool_id = self._get_volume_pool_id(volume)
        provisioning = new_pool_extraspecs['provisioning']
        new_tiering = new_pool_extraspecs['tiering']

        if not self._check_tier_pool_or_not(pool_id):
            return

        pool_tiers = self.tier_pools_dict[pool_id]

        if new_tiering == 'all':
            if provisioning == 'thin':
                tiering = ','.join(str(i) for i in pool_tiers)
            else:
                volume_size = gi_to_mi(volume['size'])
                self._check_tier_space(pool_tiers[0], pool_id, volume_size)
                tiering = str(pool_tiers[0])
        else:
            if not self._check_pool_tiering(pool_tiers, new_tiering):
                msg = _('Tiering extraspecs %(pool_name)s:%(tiering)s '
                        'can not fit in the real tiers %(pool_tier)s.') % {
                            'pool_name': pool_name,
                            'tiering': new_tiering,
                            'pool_tier': pool_tiers}
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)
            if provisioning == 'thin':
                tiering = ','.join(str(i) for i in new_tiering)
            else:
                volume_size = gi_to_mi(volume['size'])
                self._check_tier_space(new_tiering[0], pool_id, volume_size)
                tiering = str(new_tiering[0])

        rc, out = self._execute(
            'SetPartition', 'tier-resided', part_id, 'tier=%s' % tiering)
        rc, out = self._execute(
            'SetLV', 'tier-migrate', pool_id, 'part=%s' % part_id)
        self._wait_tier_migrate_complete(part_id)

    def _wait_tier_migrate_complete(self, part_id):
        start_time = int(time.time())
        timeout = self._replica_timeout

        def _inner():
            check_done = False
            try:
                rc, part_list = self._execute('ShowPartition', '-l')
                for entry in part_list:
                    if (entry['ID'] == part_id and
                            self._check_tier_migrate_completed(entry)):
                        check_done = True
            except Exception:
                check_done = False
                LOG.exception(_LE('Cannot detect tier migrate status.'))

            if check_done:
                raise loopingcall.LoopingCallDone()

            if int(time.time()) - start_time > timeout:
                msg = _('Retype volume timeout while tier migrating.')
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)

        timer = loopingcall.FixedIntervalLoopingCall(_inner)
        timer.start(interval=15).wait()

    def _check_tier_migrate_completed(self, part_info):
        status = part_info['Progress'].lower()
        if 'migrating' in status:
            LOG.info(_LI('Retype volume [%(volume_name)s] '
                         'progess [%(progess)s].'), {
                             'volume_name': part_info['Name'],
                             'progess': status})
            return False
        return True
