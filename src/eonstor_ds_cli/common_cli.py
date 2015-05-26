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
import time

from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import timeutils
from oslo_utils import units

from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder.openstack.common import loopingcall
from cinder.volume.drivers.infortrend.eonstor_ds_cli import cli_factory as cli
from cinder.volume.drivers.san import san
from cinder.volume import volume_types
from cinder.zonemanager import utils as zm_utils

LOG = logging.getLogger(__name__)

infortrend_esds_opts = [
    cfg.StrOpt('infortrend_pools_name',
               default='',
               help='Infortrend raid pool name list. '
               'It is separated with comma.'),
    cfg.StrOpt('infortrend_cli_path',
               default='/opt/bin/Infortrend/raidcmd_ESDS10.jar',
               help='The Infortrend CLI absolute path'
               'By default, it is at '
               '/opt/bin/Infortrend/raidcmd_ESDS10.jar'),
    cfg.IntOpt('infortrend_cli_max_retries',
               default=5,
               help='Maximum retry time for cli. Default is 5'),
    cfg.IntOpt('infortrend_cli_timeout',
               default=30,
               help='Default timeout for CLI copy operations in minutes. '
               'Support: migrate volume, create cloned volume and '
               'create volume from snapshot. '
               'By Default, it is 30 minutes.'),
    cfg.StrOpt('infortrend_slots_a_channels_id',
               default='0,1,2,3,4,5,6,7',
               help='Infortrend raid channel ID list on Slot A '
               'for openstack usage. It is separated with comma.'
               'By default, it is the channel 0~7'),
    cfg.StrOpt('infortrend_slots_b_channels_id',
               default='0,1,2,3,4,5,6,7',
               help='Infortrend raid channel ID list on Slot B '
               'for openstack usage. It is separated with comma.'
               'By default, it is the channel 0~7'),
]

infortrend_esds_extra_opts = [
    cfg.StrOpt('infortrend_provisioning',
               default='full',
               help='Let the volume use specific provisioning.'
               'By default, it is the full provisioning'),
    cfg.StrOpt('infortrend_tiering',
               default='0',
               help='Let the volume use specific tiering level.'
               'By default, it is the level 0.'),
]

CONF = cfg.CONF
CONF.register_opts(infortrend_esds_opts)
CONF.register_opts(infortrend_esds_extra_opts)

CLI_RC_FILTER = {
    '_create_part': {'error': _('Failed to create partition')},
    '_delete_part': {'error': _('Failed to delete partition')},
    '_set_part': {'error': _('Failed to set partition')},
    '_create_map': {
        'warning': {20: _LW('The MCS Channel is grouped')},
        'error': _('Failed to create map'),
    },
    '_delete_map': {
        'warning': {11: _LW('No mapping')},
        'error': _('Failed to delete map'),
    },
    '_create_snapshot': {'error': _('Failed to create snapshot')},
    '_delete_snapshot': {'error': _('Failed to delete snapshot')},
    '_create_replica': {'error': _('Failed to create replica')},
    '_delete_replica': {'error': _('Failed to delete replica')},
    '_create_iqn': {
        'warning': {20: _LW('IQN already existed')},
        'error': _('Failed to create iqn'),
    },
    '_delete_iqn': {
        'warning': {
            20: _LW('IQN has been used to create map'),
            11: _LW('No such host alias name'),
        },
        'error': _('Failed to delete iqn'),
    },
    '_show_lv': {'error': _('Failed to get lv info')},
    '_show_part': {'error': _('Failed to get partition info')},
    '_show_snapshot': {'error': _('Failed to get snapshot info')},
    '_show_device': {'error': _('Failed to get device info')},
    '_show_channel': {'error': _('Failed to get channel info')},
    '_show_map': {'error': _('Failed to get map info')},
    '_show_net': {'error': _('Failed to get network info')},
    '_show_license': {'error': _('Failed to get license info')},
    '_show_replica': {'error': _('Failed to get replica info')},
    '_show_wwn': {'error': _('Failed to get wwn info')},
    '_show_iqn': {'error': _('Failed to get iqn info')},
}


def return_code_handler(func):
    def inner(self, *args):
        func_name = func.__name__
        LOG.debug('Enter %(method)s', {'method': func_name})

        rc, out = func(self, *args)

        if rc != 0:
            if ('warning' in CLI_RC_FILTER[func_name] and
                    rc in CLI_RC_FILTER[func_name]['warning']):
                LOG.warning(CLI_RC_FILTER[func_name]['warning'][rc])
            else:
                msg = CLI_RC_FILTER[func_name]['error']
                LOG.error(msg)
                raise exception.InfortrendCliException(
                    err=msg, param=args, rc=rc, out=out)
        return rc, out
    return inner


def log_func(func):
    def inner(self, *args, **kwargs):
        LOG.debug('Enter %(method)s', {'method': func.__name__})
        start = timeutils.utcnow()
        ret = func(self, *args, **kwargs)
        end = timeutils.utcnow()
        LOG.debug(
            'Leave %(method)s '
            'Spent %(time)s sec '
            'Return %(ret)s', {
                'method': func.__name__,
                'time': timeutils.delta_seconds(start, end),
                'ret': ret})
        return ret
    return inner


def mi_to_gi(mi_size):
    return mi_size * units.Mi / units.Gi


def gi_to_mi(gi_size):
    return gi_size * units.Gi / units.Mi


class InfortrendCommon(object):

    """The Infortrend's Common Command using CLI.

    Version history:
        1.0.0 - Initial driver
    """

    VERSION = '1.0.0'

    constants = {
        'ISCSI_PORT': 3260,
        'MAX_LUN_MAP_PER_CHL': 128
    }

    provisioning_values = ['thin', 'full']

    tiering_values = ['0', '2', '3', '4']

    def __init__(self, protocol, configuration=None):

        self.protocol = protocol
        self.configuration = configuration
        self.configuration.append_config_values(san.san_opts)
        self.configuration.append_config_values(infortrend_esds_opts)
        self.configuration.append_config_values(infortrend_esds_extra_opts)

        self.iscsi_multipath = self.configuration.use_multipath_for_image_xfer
        self.path = self.configuration.infortrend_cli_path
        self.password = self.configuration.san_password
        self.ip = self.configuration.san_ip
        self.cli_retry_time = self.configuration.infortrend_cli_max_retries
        self.cli_timeout = self.configuration.infortrend_cli_timeout * 60
        self.iqn = "iqn.2002-10.com.infortrend:raid.uid%s.%s%s%s"

        if self.ip == '':
            msg = _('san_ip is not set.')
            LOG.error(msg)
            raise exception.InfortrendDriverException(data=msg)

        self.fc_lookup_service = zm_utils.create_lookup_service()

        self._volume_stats = None
        self._model_type = 'R'
        self._replica_timeout = self.cli_timeout

        self.map_dict = {
            'slot_a': {},
            'slot_b': {},
        }
        self.map_dict_init = False
        self.mcs_dict = {
            'slot_a': {},
            'slot_b': {},
        }

        self._init_pool_list()
        self._init_channel_list()

        self.cli_conf = {
            'path': self.path,
            'password': self.password,
            'ip': self.ip,
            'cli_retry_time': int(self.cli_retry_time),
        }

    def _init_pool_list(self):
        pools_name = self.configuration.infortrend_pools_name
        if pools_name == '':
            msg = _('Pools name is not set.')
            LOG.error(msg)
            raise exception.InfortrendDriverException(data=msg)

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

    def _execute_command(self, cli_type, *args, **kwargs):
        command = getattr(cli, cli_type)
        return command(self.cli_conf).execute(*args, **kwargs)

    def _execute(self, *args, **kwargs):
        return self._execute_command('ExecuteCommand', *args, **kwargs)

    @return_code_handler
    def _create_part(self, *args):
        return self._execute_command('CreatePartition', *args)

    @return_code_handler
    def _delete_part(self, *args):
        return self._execute_command('DeletePartition', *args)

    @return_code_handler
    def _set_part(self, *args):
        return self._execute_command('SetPartition', *args)

    @return_code_handler
    def _create_map(self, *args):
        return self._execute_command('CreateMap', *args)

    @return_code_handler
    def _delete_map(self, *args):
        return self._execute_command('DeleteMap', *args)

    @return_code_handler
    def _create_snapshot(self, *args):
        return self._execute_command('CreateSnapshot', *args)

    @return_code_handler
    def _delete_snapshot(self, *args):
        return self._execute_command('DeleteSnapshot', *args)

    @return_code_handler
    def _create_replica(self, *args):
        return self._execute_command('CreateReplica', *args)

    @return_code_handler
    def _delete_replica(self, *args):
        return self._execute_command('DeleteReplica', *args)

    @return_code_handler
    def _create_iqn(self, *args):
        return self._execute_command('CreateIQN', *args)

    @return_code_handler
    def _delete_iqn(self, *args):
        return self._execute_command('DeleteIQN', *args)

    @return_code_handler
    def _show_lv(self, *args):
        return self._execute_command('ShowLV', *args)

    @return_code_handler
    def _show_part(self, *args):
        return self._execute_command('ShowPartition', *args)

    @return_code_handler
    def _show_snapshot(self, *args):
        return self._execute_command('ShowSnapshot', *args)

    @return_code_handler
    def _show_device(self, *args):
        return self._execute_command('ShowDevice', *args)

    @return_code_handler
    def _show_channel(self, *args):
        return self._execute_command('ShowChannel', *args)

    @return_code_handler
    def _show_map(self, *args):
        return self._execute_command('ShowMap', *args)

    @return_code_handler
    def _show_net(self, *args):
        return self._execute_command('ShowNet', *args)

    @return_code_handler
    def _show_license(self, *args):
        return self._execute_command('ShowLicense', *args)

    @return_code_handler
    def _show_replica(self, *args):
        return self._execute_command('ShowReplica', *args)

    @return_code_handler
    def _show_wwn(self, *args):
        return self._execute_command('ShowWWN', *args)

    @return_code_handler
    def _show_iqn(self, *args):
        return self._execute_command('ShowIQN', *args)

    @log_func
    def _init_map_info(self, multipath=False):
        if not self.map_dict_init:

            rc, channel_info = self._show_channel()

            if 'BID' in channel_info[0]:
                self._model_type = 'R'
            else:
                self._model_type = 'G'

            self._set_iscsi_channel_id(channel_info, 'slot_a', multipath)

            if multipath and self._model_type == 'R':
                self._set_iscsi_channel_id(channel_info, 'slot_b', multipath)

            self.map_dict_init = True

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
        rc, map_info = self._show_map()

        self._update_map_info_by_slot(map_info, 'slot_a')

        if multipath and self._model_type == 'R':
            self._update_map_info_by_slot(map_info, 'slot_b')

    @log_func
    def _update_map_info_by_slot(self, map_info, slot_key):
        for key, value in self.map_dict[slot_key].items():
            self.map_dict[slot_key][key] = list(
                range(self.constants['MAX_LUN_MAP_PER_CHL']))

        target_id = 0 if slot_key == 'slot_a' else 1
        if self.protocol == 'FC':
            target_id += 112

        if len(map_info) > 0 and isinstance(map_info, list):
            for entry in map_info:
                ch = entry['Ch']
                lun = entry['LUN']
                if (ch in self.map_dict[slot_key].keys() and
                        entry['Target'] == str(target_id) and
                        int(lun) in self.map_dict[slot_key][ch]):

                    self.map_dict[slot_key][ch].remove(int(lun))

    @log_func
    def _set_iscsi_channel_id(
            self, channel_info, controller='slot_a', multipath=False):

        if self.protocol == 'iSCSI':
            check_channel_type = 'NETWORK'
        else:
            check_channel_type = 'FIBRE'

        for entry in channel_info:
            if entry['Type'] == check_channel_type:

                if entry['Ch'] in self.channel_list[controller]:
                    self.map_dict[controller][entry['Ch']] = []

                    self._update_mcs_dict(
                        entry['Ch'], entry['MCS'], controller)

    def _update_mcs_dict(self, channel_id, mcs_id, controller):
        """Record the iSCSI MCS topology

        # R model with mcs, but it not working with iscsi multipath
        mcs_dict = {
            'slot_a': {
                '0': ['0', '1'],
                '1': ['2']
            },
            'slot_b': {
                '0': ['0', '1'],
                '1': ['2']
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

    def _check_tiers_setup(self):
        tiering = self.configuration.infortrend_tiering
        if tiering != '0':
            self._check_extraspec_value(
                tiering, self.tiering_values)
            tier_levels_list = list(range(int(tiering)))
            tier_levels_list = list(map(str, tier_levels_list))

            rc, lv_info = self._show_lv('tier')

            for pool in self.pool_list:
                support_tier_levels = tier_levels_list[:]
                for entry in lv_info:
                    if (entry['LV-Name'] == pool and
                            entry['Tier'] in support_tier_levels):
                        support_tier_levels.remove(entry['Tier'])
                    if len(support_tier_levels) == 0:
                        break
                if len(support_tier_levels) != 0:
                    msg = _('Please create %(tier_levels)s '
                            'tier in pool %(pool)s in advance!') % {
                                'tier_levels': support_tier_levels,
                                'pool': pool}
                    LOG.error(msg)
                    raise exception.InfortrendDriverException(err=msg)

    def _check_pools_setup(self):
        pool_list = self.pool_list[:]

        rc, lv_info = self._show_lv()

        for lv in lv_info:
            if lv['Name'] in pool_list:
                pool_list.remove(lv['Name'])
            if len(pool_list) == 0:
                break

        if len(pool_list) != 0:
            msg = _('Please create %(pool_list)s pool in advance!') % {
                'pool_list': pool_list}
            LOG.error(msg)
            raise exception.InfortrendDriverException(err=msg)

    def check_for_setup_error(self):
        self._check_pools_setup()
        self._check_tiers_setup()

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
        LOG.info(_LI('Create Volume %(volume_id)s done'), {
            'volume_id': volume_id})
        return model_update

    def _create_partition_by_default(self, volume):
        pool_id = self._get_target_pool_id(volume)
        self._create_partition_with_pool(volume, pool_id)

    def _create_partition_with_pool(self, volume, pool_id):
        volume_id = volume['id'].replace('-', '')
        volume_size = gi_to_mi(volume['size'])

        extraspecs = self._get_extraspecs_dict(volume['volume_type_id'])

        provisioning = self._get_extraspecs_value(extraspecs, 'provisioning')
        tiering = self._get_extraspecs_value(extraspecs, 'tiering')

        extraspecs_dict = {}
        cmd = ''
        if provisioning == 'thin':
            provisioning = int(volume_size * 0.2)
            extraspecs_dict['provisioning'] = provisioning
            extraspecs_dict['init'] = 'disable'
        else:
            self._check_extraspec_value(
                provisioning, self.provisioning_values)

        if tiering != '0':
            self._check_extraspec_value(
                tiering, self.tiering_values)
            tier_levels_list = list(range(int(tiering)))
            tier_levels_list = list(map(str, tier_levels_list))
            self._check_tiering_existing(tier_levels_list, pool_id)
            extraspecs_dict['provisioning'] = 0
            extraspecs_dict['init'] = 'disable'

        if extraspecs_dict:
            cmd = self._create_part_parameters_str(extraspecs_dict)

        self._create_part(pool_id, volume_id, 'size=%s' % volume_size, cmd)

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

        cmd = ' '.join(parameters_list)
        return cmd

    def _check_tiering_existing(self, tier_levels, pool_id):
        rc, lv_info = self._show_lv('tier')

        for entry in lv_info:
            if entry['LV-ID'] == pool_id and entry['Tier'] in tier_levels:
                tier_levels.remove(entry['Tier'])
                if len(tier_levels) == 0:
                    break
        if len(tier_levels) != 0:
            msg = _('Have not created %(tier_levels)s tier(s)') % {
                'tier_levels': tier_levels}
            LOG.error(msg)
            raise exception.InfortrendDriverException(err=msg)

    @log_func
    def _create_map_with_lun_filter(
            self, part_id, channel_id, lun_id, host, controller='slot_a'):

        target_id, host_filter = self._create_target_id_and_host_filter(
            controller, host)

        self._create_map(
            'part', part_id, channel_id, str(target_id), lun_id, host_filter)

    @log_func
    def _create_map_with_mcs(
            self, part_id, channel_list, lun_id, host, controller='slot_a'):

        target_id, host_filter = self._create_target_id_and_host_filter(
            controller, host)

        map_channel_id = None
        for channel_id in channel_list:
            rc, out = self._create_map(
                'part', part_id, channel_id,
                str(target_id), lun_id, host_filter)
            if rc == 0:
                map_channel_id = channel_id
                break

        if map_channel_id is None:
            msg = _('Failed to create map on mcs, no channel can map')
            LOG.error(msg)
            raise exception.InfortrendDriverException(err=msg)

        return map_channel_id

    def _create_target_id_and_host_filter(self, controller, host):
        target_id = 0 if controller == 'slot_a' else 1

        if self.protocol == 'iSCSI':
            host_filter = 'iqn=%s' % host
        else:
            host_filter = 'wwn=%s' % host
            target_id += 112

        return target_id, host_filter

    def _get_extraspecs_dict(self, volume_type_id):
        extraspecs = {}
        if volume_type_id:
            extraspecs = volume_types.get_volume_type_extra_specs(
                volume_type_id)

        return extraspecs

    def _get_extraspecs_value(self, extraspecs, key):
        value = None
        if key == 'provisioning':
            if (extraspecs and
                    'infortrend_provisioning' in extraspecs.keys()):
                value = extraspecs['infortrend_provisioning'].lower()
            else:
                value = self.configuration.infortrend_provisioning.lower()
        elif key == 'tiering':
                value = self.configuration.infortrend_tiering
        return value

    def _select_most_free_capacity_pool_id(self, lv_info):
        largest_free_capacity_gb = 0.0
        dest_pool_id = None

        for lv in lv_info:
            if lv['Name'] in self.pool_list:
                available_space = float(lv['Available'].split(' ', 1)[0])
                free_capacity_gb = round(mi_to_gi(available_space))
                if free_capacity_gb > largest_free_capacity_gb:
                    largest_free_capacity_gb = free_capacity_gb
                    dest_pool_id = lv['ID']
        return dest_pool_id

    def _get_target_pool_id(self, volume):
        extraspecs = self._get_extraspecs_dict(volume['volume_type_id'])
        pool_id = None
        rc, lv_info = self._show_lv()

        if 'pool_name' in extraspecs.keys():
            poolname = extraspecs['pool_name']

            for entry in lv_info:
                if entry['Name'] == poolname:
                    pool_id = entry['ID']
        else:
            pool_id = self._select_most_free_capacity_pool_id(lv_info)

        if pool_id is None:
            msg = _('Failed to get pool id with volume %(volume_id)s') % {
                'volume_id': volume['id']}
            LOG.error(msg)
            raise exception.InfortrendAPIException(err=msg)

        return pool_id

    def _get_system_id(self, system_ip):
        rc, device_info = self._show_device()

        for entry in device_info:
            if system_ip == entry['Connected-IP']:
                return str(int(entry['ID'], 16))
        return None

    @log_func
    def _get_lun_id(self, ch_id, controller='slot_a'):
        lun_id = -1

        if len(self.map_dict[controller][ch_id]) > 0:
            lun_id = self.map_dict[controller][ch_id][0]
            self.map_dict[controller][ch_id].remove(lun_id)

        if lun_id == -1:
            msg = _('LUN number is out of bound '
                    'on channel id: %(ch_id)s') % {'ch_id': ch_id}
            LOG.error(msg)
            raise exception.InfortrendDriverException(err=msg)
        else:
            return lun_id

    @log_func
    def _get_mapping_info(self, multipath):
        if self.iscsi_multipath or multipath:
            return self._get_mapping_info_with_mcs()
        else:
            return self._get_mapping_info_with_normal()

    def _get_mapping_info_with_mcs(self):
        """Get the minimun mapping channel id and multi lun id mapping info

        # R model with mcs
        map_chl = {
            'slot_a': ['0', '1']
        }
        map_lun = ['0']

        # G model with mcs
        map_chl = {
            'slot_a': ['1', '2']
        }
        map_lun = ['0']

        :returns: minimun mapping channel id per slot and multi lun id
        """
        map_chl = {
            'slot_a': []
        }

        min_lun_num = 0
        map_mcs_group = None
        for mcs in self.mcs_dict['slot_a']:
            if len(self.mcs_dict['slot_a'][mcs]) > 1:
                if min_lun_num < self._get_mcs_channel_lun_map_num(mcs):
                    min_lun_num = self._get_mcs_channel_lun_map_num(mcs)
                    map_mcs_group = mcs

        if map_mcs_group is None:
            msg = _('Raid did not have MCS Channel.')
            LOG.error(msg)
            raise exception.InfortrendDriverException(err=msg)

        map_chl['slot_a'] = self.mcs_dict['slot_a'][map_mcs_group]
        map_lun = self._get_mcs_channel_lun_map(map_chl['slot_a'])
        return map_chl, map_lun, map_mcs_group

    def _get_mcs_channel_lun_map_num(self, mcs_id):
        lun_num = 0
        for channel in self.mcs_dict['slot_a'][mcs_id]:
            lun_num += len(self.map_dict['slot_a'][channel])
        return lun_num

    def _get_mcs_channel_lun_map(self, channel_list):
        """Find the common lun id in mcs channel"""

        map_lun = []
        for lun_id in range(self.constants['MAX_LUN_MAP_PER_CHL']):
            check_map = True
            for channel_id in channel_list:
                if lun_id not in self.map_dict['slot_a'][channel_id]:
                    check_map = False
            if check_map:
                map_lun.append(str(lun_id))
                break
        return map_lun

    @log_func
    def _get_mapping_info_with_normal(self):
        """Get the minimun mapping channel id and lun id mapping info

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
        mcs_id = self._get_mcs_id_by_channel_id(ret_chl)

        map_chl['slot_a'].append(ret_chl)
        map_lun.append(str(lun_id))

        return map_chl, map_lun, mcs_id

    @log_func
    def _get_minimun_mapping_channel_id(self, controller):
        empty_lun_num = 0
        min_map_chl = -1

        for key, value in self.map_dict[controller].items():
            if empty_lun_num < len(value):
                min_map_chl = key
                empty_lun_num = len(value)

        if int(min_map_chl) < 0:
            msg = _('LUN map overflow on every channel')
            LOG.error(msg)
            raise exception.InfortrendDriverException(err=msg)
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

    def _get_mcs_id_by_channel_id(self, channel_id):
        mcs_id = None

        for mcs in self.mcs_dict['slot_a']:
            if channel_id in self.mcs_dict['slot_a'][mcs]:
                mcs_id = mcs
                break

        if mcs_id is None:
            msg = _('Cannot get mcs_id by channel id=%(channel_id)s') % {
                'channel_id': channel_id}
            LOG.error(msg)
            raise exception.InfortrendDriverException(err=msg)

        return mcs_id

    def _concat_provider_location(self, model_dict):
        return '@'.join([i + '^' + str(model_dict[i]) for i in model_dict])

    def delete_volume(self, volume):
        """Delete the specific volume."""

        volume_id = volume['id'].replace('-', '')
        has_pair = False
        have_map = False

        part_id = self._extract_specific_provider_location(
            volume['provider_location'], 'partition_id')

        (check_exist, have_map, part_id) = (
            self._check_volume_exist(volume_id, part_id)
        )

        if not check_exist:
            LOG.warning(_LW('Volume %(volume_id)s already deleted'), {
                'volume_id': volume_id})
            return

        rc, replica_list = self._show_replica('-l')

        for entry in replica_list:
            if (volume_id == entry['Source-Name'] and
                    part_id == entry['Source']):
                if not self._check_replica_completed(entry):
                    has_pair = True
                    LOG.warning(_LW('Volume still %(status)s '
                                    'Cannot delete volume.'), {
                                        'status': entry['Status']})
                else:
                    have_map = entry['Source-Mapped'] == 'Yes'
                    self._delete_replica(entry['Pair-ID'], '-y')

            elif (volume_id == entry['Target-Name'] and
                    part_id == entry['Target']):
                have_map = entry['Target-Mapped'] == 'Yes'
                self._delete_replica(entry['Pair-ID'], '-y')

        if not has_pair:

            rc, snapshot_list = self._show_snapshot('part=%s' % part_id)

            for snapshot in snapshot_list:
                si_has_pair = self._delete_pair_with_snapshot(
                    snapshot['SI-ID'], replica_list)

                if si_has_pair:
                    msg = _('Failed to delete SI '
                            'for volume_id: %(volume_id)s '
                            'because it has pair') % {
                                'volume_id': volume_id}
                    LOG.error(msg)
                    raise exception.InfortrendDriverException(err=msg)

                self._delete_snapshot(snapshot['SI-ID'], '-y')

            rc, map_info = self._show_map('part=%s' % part_id)

            if have_map or len(map_info) > 0:
                self._delete_map('part', part_id, '-y')

            self._delete_part(part_id, '-y')

            LOG.info(_LI('Delete Volume %(volume_id)s done'), {
                'volume_id': volume_id})
        else:
            msg = _('Failed to delete volume '
                    'for volume_id: %(volume_id)s '
                    'because it has pair') % {
                        'volume_id': volume_id}
            LOG.error(msg)
            raise exception.InfortrendDriverException(err=msg)

    def _check_replica_completed(self, replica):
        if ((replica['Type'] == 'Copy' and replica['Status'] == 'Completed') or
                (replica['Type'] == 'Mirror' and
                    replica['Status'] == 'Mirror')):
            return True

        return False

    def _check_volume_exist(self, volume_id, part_id):
        check_exist = False
        have_map = False
        result_part_id = part_id

        rc, part_list = self._show_part('-l')

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

        @lockutils.synchronized(
            'snapshot-' + src_part_id, 'infortrend-', True)
        def do_create_snapshot():
            self._create_snapshot('part', src_part_id)
            rc, tmp_snapshot_list = self._show_snapshot(
                'part=%s' % src_part_id)
            return tmp_snapshot_list

        snapshot_list = do_create_snapshot()

        model_update = self._create_volume_from_snapshot_id(
            volume, snapshot_list[-1]['SI-ID'], 'Cloned')

        LOG.info(_LI('Create Cloned Volume %(volume_id)s done'), {
            'volume_id': volume['id']})
        return model_update

    def _extract_specific_provider_location(self, provider_location, key):
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

        LOG.info(_LI('Create export done from Volume %(volume_id)s'), {
            'volume_id': volume['id']})

        return {'provider_location': model_update}

    def get_volume_stats(self, refresh=False):
        """Get volume status

        If refresh is True, update the status first
        """
        if self._volume_stats is None or refresh:
            self._update_volume_stats()

        LOG.info(_LI(
            'Successfully update volume stats '
            'backend: %(volume_backend_name)s '
            'vendor: %(vendor_name)s '
            'driver version: %(driver_version)s '
            'storage protocol: %(storage_protocol)s'), self._volume_stats)

        return self._volume_stats

    def _update_volume_stats(self):

        backend_name = self.configuration.safe_get('volume_backend_name')

        data = {
            'volume_backend_name': backend_name,
            'vendor_name': 'Infortrend',
            'driver_version': self.VERSION,
            'storage_protocol': self.protocol,
            'pools': self._update_pools_stats(),
        }
        self._volume_stats = data

    def _update_pools_stats(self):
        enable_specs_dict = self._get_enable_specs_on_array()

        if 'Thin Provisioning' in enable_specs_dict.keys():
            provisioning = 'thin'
            provisioning_support = True
        else:
            provisioning = 'full'
            provisioning_support = False

        rc, pools_info = self._show_lv()
        pools = []

        for pool in pools_info:
            if pool['Name'] in self.pool_list:
                total_space = float(pool['Size'].split(' ', 1)[0])
                available_space = float(pool['Available'].split(' ', 1)[0])
                provisioning_space = total_space - available_space

                total_capacity_gb = round(mi_to_gi(total_space), 2)
                free_capacity_gb = round(mi_to_gi(available_space), 2)
                provisioned_capacity_gb = round(
                    mi_to_gi(provisioning_space), 2)

                provisioning_factor = self.configuration.safe_get(
                    'max_over_subscription_ratio')
                new_pool = {
                    'pool_name': pool['Name'],
                    'pool_id': pool['ID'],
                    'total_capacity_gb': total_capacity_gb,
                    'free_capacity_gb': free_capacity_gb,
                    'reserved_percentage': 0,
                    'QoS_support': False,
                    'provisioned_capacity_gb': provisioned_capacity_gb,
                    'max_over_subscription_ratio': provisioning_factor,
                    'thin_provisioning_support': provisioning_support,
                    'thick_provisioning_support': True,
                    'infortrend_provisioning': provisioning,
                }
                pools.append(new_pool)
        return pools

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""

        snapshot_id = snapshot['id'].replace('-', '')
        volume_id = snapshot['volume_id'].replace('-', '')

        LOG.debug('Create Snapshot %(snapshot)s volume %(volume)s',
                  {'snapshot': snapshot_id, 'volume': volume_id})

        model_update = {}
        part_id = self._get_part_id(volume_id)

        if part_id is None:
            msg = _('Failed to get Partition ID for volume %(volume_id)s.') % {
                'volume_id': volume_id}
            LOG.error(msg)
            raise exception.InfortrendAPIException(err=msg)

        @lockutils.synchronized(
            'snapshot-' + part_id, 'infortrend-', True)
        def do_create_snapshot():
            self._create_snapshot('part', part_id)
            rc, tmp_snapshot_list = self._show_snapshot('part=%s' % part_id)
            return tmp_snapshot_list

        snapshot_list = do_create_snapshot()

        LOG.info(_LI(
            'Create success '
            'Snapshot: %(snapshot)s '
            'Snapshot ID in raid: %(raid_snapshot_id)s '
            'volume: %(volume)s'), {
                'snapshot': snapshot_id,
                'raid_snapshot_id': snapshot_list[-1]['SI-ID'],
                'volume': volume_id})
        model_update['provider_location'] = snapshot_list[-1]['SI-ID']
        return model_update

    def delete_snapshot(self, snapshot):
        """Delete the snapshot"""

        snapshot_id = snapshot['id'].replace('-', '')
        volume_id = snapshot['volume_id'].replace('-', '')

        LOG.debug('Delete Snapshot %(snapshot)s volume %(volume)s',
                  {'snapshot': snapshot_id, 'volume': volume_id})

        raid_snapshot_id = self._get_raid_snapshot_id(snapshot)

        if raid_snapshot_id:

            rc, replica_list = self._show_replica('-l')

            has_pair = self._delete_pair_with_snapshot(
                raid_snapshot_id, replica_list)

            if not has_pair:
                self._delete_snapshot(raid_snapshot_id, '-y')

                LOG.info(_LI('Delete Snapshot %(snapshot_id)s done'), {
                    'snapshot_id': snapshot_id})
            else:
                msg = _('Failed to delete snapshot '
                        'for snapshot_id: %s '
                        'because it has pair') % snapshot_id
                LOG.error(msg)
                raise exception.InfortrendDriverException(err=msg)
        else:
            msg = _(
                'Failed to get Raid Snapshot ID '
                'from Snapshot %(snapshot_id)s.') % {
                    'snapshot_id': snapshot_id}
            LOG.error(msg)
            raise exception.InfortrendAPIException(err=msg)

    def _get_raid_snapshot_id(self, snapshot):
        if 'provider_location' not in snapshot:
            LOG.warning(_LW(
                'Failed to get Raid Snapshot ID and '
                'did not store in snapshot'))
            return None
        return snapshot['provider_location']

    def _delete_pair_with_snapshot(self, snapshot_id, replica_list):
        has_pair = False
        for entry in replica_list:
            if entry['Source'] == snapshot_id:

                if not self._check_replica_completed(entry):
                    has_pair = True
                    LOG.warning(_LW(
                        'Snapshot still %(status)s Cannot delete snapshot.'), {
                            'status': entry['Status']})
                else:
                    self._delete_replica(entry['Pair-ID'], '-y')
        return has_pair

    def _get_part_id(self, volume_id, pool_id=None, part_list=None):
        if part_list is None:
            rc, part_list = self._show_part()
        for entry in part_list:
            if pool_id is None:
                if entry['Name'] == volume_id:
                    return entry['ID']
            else:
                if entry['Name'] == volume_id and entry['LV-ID'] == pool_id:
                    return entry['ID']
        return None

    def create_volume_from_snapshot(self, volume, snapshot):
        raid_snapshot_id = self._get_raid_snapshot_id(snapshot)

        if raid_snapshot_id is None:
            msg = _('Failed to get Raid Snapshot ID '
                    'from snapshot: %(snapshot_id)s') % {
                        'snapshot_id': snapshot['id']}
            LOG.error(msg)
            raise exception.InfortrendAPIException(err=msg)

        model_update = self._create_volume_from_snapshot_id(
            volume, raid_snapshot_id, 'Snapshot')

        LOG.info(_LI(
            'Create Volume %(volume_id)s from '
            'snapshot %(snapshot_id)s done'), {
                'volume_id': volume['id'],
                'snapshot_id': snapshot['id']})

        return model_update

    def _create_volume_from_snapshot_id(self, volume, raid_snapshot_id, type):
        # create the target volume for volume copy
        dst_volume_id = volume['id'].replace('-', '')

        self._create_partition_by_default(volume)

        dst_part_id = self._get_part_id(dst_volume_id)
        # prepare return value
        system_id = self._get_system_id(self.ip)
        model_dict = {
            'system_id': system_id,
            'partition_id': dst_part_id,
        }

        model_info = self._concat_provider_location(model_dict)
        model_update = {"provider_location": model_info}

        # clone the volume from the snapshot
        self._create_replica(
            'Cinder-%s' % type, 'si', raid_snapshot_id, 'part', dst_part_id)

        self._wait_replica_complete(dst_part_id)

        return model_update

    @lockutils.synchronized('connection', 'infortrend-', True)
    def initialize_connection(self, volume, connector):
        if self.protocol == 'iSCSI':
            multipath = connector.get('multipath', False)
            return self._initialize_connection_iscsi(
                volume, connector, multipath)
        elif self.protocol == 'FC':
            return self._initialize_connection_fc(
                volume, connector)
        else:
            msg = _('Unknown protocol')
            LOG.error(msg)
            raise exception.InfortrendDriverException(err=msg)

    def _initialize_connection_fc(self, volume, connector):
        self._init_map_info(True)
        self._update_map_info(True)

        map_lun, target_wwpns, initiator_target_map = (
            self._do_fc_connection(volume, connector)
        )

        properties = self._generate_fc_connection_properties(
            map_lun, target_wwpns, initiator_target_map)

        LOG.info(_LI('Successfully initialize connection '
                     'target_wwn: %(target_wwn)s '
                     'initiator_target_map: %(initiator_target_map)s '
                     'lun: %(target_lun)s '), properties['data'])
        return properties

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

        for initiator_wwpn in initiator_target_map:
            for target_wwpn in initiator_target_map[initiator_wwpn]:
                channel_id = wwpn_channel_info[target_wwpn]['channel']
                controller = wwpn_channel_info[target_wwpn]['slot']
                self._create_map_with_lun_filter(
                    part_id, channel_id, map_lun, initiator_wwpn,
                    controller=controller)

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
                'access_mode': 'rw',
                'initiator_target_map': initiator_target_map,
            },
        }

    @log_func
    def _initialize_connection_iscsi(self, volume, connector, multipath):
        self._init_map_info(multipath)
        self._update_map_info(multipath)

        volume_id = volume['id'].replace('-', '')

        partition_data = self._extract_all_provider_location(
            volume['provider_location'])  # system_id, part_id

        part_id = partition_data['partition_id']

        if part_id is None:
            part_id = self._get_part_id(volume_id)

        self._set_host_iqn(connector['initiator'])

        map_chl, map_lun, mcs_id = self._get_mapping_info(multipath)

        lun_id = map_lun[0]

        if self.iscsi_multipath or multipath:
            channel_id = self._create_map_with_mcs(
                part_id, map_chl['slot_a'], lun_id, connector['initiator'])
        else:
            channel_id = map_chl['slot_a'][0]

            self._create_map_with_lun_filter(
                part_id, channel_id, lun_id, connector['initiator'])

        rc, net_list = self._show_net()
        ip = self._get_ip_by_channel(channel_id, net_list)

        if ip is None:
            msg = _(
                'Failed to get ip on Channel %(channel_id)s '
                'with volume_id %(volume_id)s') % {
                    'channel_id': channel_id, 'volume_id': volume_id}
            LOG.error(msg)
            raise exception.InfortrendDriverException(err=msg)

        partition_data = self._combine_channel_lun_target_id(
            partition_data, mcs_id, lun_id)

        property_value = [{
            'lun_id': partition_data['lun_id'],
            'iqn': self._generate_iqn(partition_data),
            'ip': ip,
            'port': self.constants['ISCSI_PORT'],
        }]

        properties = self._generate_iscsi_connection_properties(
            property_value, volume)
        LOG.info(_LI('Successfully initialize connection '
                     'volume: %(volume_id)s'), properties['data'])
        return properties

    @log_func
    def _combine_channel_lun_target_id(
            self, partition_data, mcs_id, lun_id, controller='slot_a'):

        target_id = 0 if controller == 'slot_a' else 1
        slot_id = 1 if controller == 'slot_a' else 2

        partition_data['mcs_id'] = mcs_id
        partition_data['lun_id'] = lun_id
        partition_data['target_id'] = target_id
        partition_data['slot_id'] = slot_id

        return partition_data

    def _set_host_iqn(self, host_iqn):

        rc, iqn_list = self._show_iqn()

        check_iqn_exist = False
        for entry in iqn_list:
            if entry['IQN'] == host_iqn:
                check_iqn_exist = True

        if not check_iqn_exist:
            self._create_iqn(host_iqn, self._truncate_host_name(host_iqn))

    def _truncate_host_name(self, iqn):
        if len(iqn) > 16:
            return iqn[-16:]
        else:
            return iqn

    def _extract_lun_map(self, mapping):
        """Extract lun map

        format: 'CH:1/ID:0/LUN:0, CH:1/ID:0/LUN:1, CH:2/ID:0/LUN:0'
        """
        mapping_list = mapping.split(', ')
        lun_map = []

        for map_entry in mapping_list:
            map_entry_dict = {}
            entry_info_list = map_entry.split('/')

            for entry_info in entry_info_list:
                temp_entry_info = entry_info.split(':', 1)
                map_entry_dict[temp_entry_info[0]] = temp_entry_info[1]

            lun_map.append({
                'channel_id': map_entry_dict['CH'],
                'target_id': map_entry_dict['ID'],
                'lun_id': map_entry_dict['LUN'],
            })
        return lun_map

    @log_func
    def _generate_iqn(self, partition_data):
        return self.iqn % (
            partition_data['system_id'],
            partition_data['mcs_id'],
            partition_data['target_id'],
            partition_data['slot_id'])

    @log_func
    def _get_ip_by_channel(
            self, channel_id, net_list, controller='slot_a'):

        slot_name = 'slotA' if controller == 'slot_a' else 'slotB'

        for entry in net_list:
            if entry['ID'] == channel_id and entry['Slot'] == slot_name:
                return entry['IPv4']
        return None

    def _get_wwpn_by_channel(
            self, channel_id, wwn_list, controller='slot_a'):

        if self._model_type == 'R':
            slot_name = 'AID:112' if controller == 'slot_a' else 'BID:113'
        else:
            slot_name = 'ID:112'

        for entry in wwn_list:
            if entry['CH'] == channel_id and entry['ID'] == slot_name:
                return entry['WWPN']
        return None

    def _get_wwpn_list(self):
        rc, wwn_list = self._show_wwn()

        wwpn_list = []
        wwpn_channel_info = {}

        for entry in wwn_list:
            channel_id = entry['CH']
            if 'BID:113' == entry['ID']:
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
            self, property_value, volume):

        properties = {}
        discovery_exist = False

        specific_property = property_value[0]

        discovery_ip = '%s:%s' % (
            specific_property['ip'], specific_property['port'])
        discovery_iqn = specific_property['iqn']

        if self._do_iscsi_discovery(discovery_iqn, discovery_ip):
            properties['target_portal'] = discovery_ip
            properties['target_iqn'] = discovery_iqn
            properties['target_lun'] = int(specific_property['lun_id'])
            discovery_exist = True

        if not discovery_exist:
            msg = _('Could not find iSCSI target for %(volume_id)s') % {
                'volume_id': volume['id']}
            LOG.error(msg)
            raise exception.InfortrendDriverException(err=msg)

        properties['target_discovered'] = discovery_exist
        properties['volume_id'] = volume['id']

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
        rc, out = self._execute('iscsiadm', '-m', 'discovery',
                                '-t', 'sendtargets', '-p',
                                target_ip,
                                run_as_root=True)
        if rc != 0:
            LOG.error(_LE(
                'Can not discovery in %(target_ip)s with %(target_iqn)s'), {
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

        self._set_part('expand', part_id, expand_command)

        LOG.info(_LI(
            'Successfully extended volume %(volume_id)s '
            'size %(size)s'), {
                'volume_id': volume['id'], 'size': new_size})

    @lockutils.synchronized('connection', 'infortrend-', True)
    def terminate_connection(self, volume, connector):
        volume_id = volume['id'].replace('-', '')
        multipath = connector.get('multipath', False)

        part_id = self._extract_specific_provider_location(
            volume['provider_location'], 'partition_id')

        if part_id is None:
            part_id = self._get_part_id(volume_id)

        self._delete_map('part', part_id, '-y')
        if self.protocol == 'iSCSI':
            self._delete_iqn(self._truncate_host_name(connector['initiator']))
        self._update_map_info(multipath)

        LOG.info(_LI(
            'Successfully terminated connection for volume %(volume_id)s'), {
                'volume_id': volume['id']})

    def migrate_volume(self, volume, host):
        is_valid, dst_pool_id = (
            self._is_valid_for_storage_assisted_migration(host)
        )
        if not is_valid:
            return (False, None)

        model_dict = self._migrate_volume_with_pool(
            volume, dst_pool_id)

        model_update = {
            "provider_location": self._concat_provider_location(model_dict),
        }

        LOG.info(_LI('Migrate Volume %(volume_id)s done'), {
            'volume_id': volume['id']})

        return (True, model_update)

    def _is_valid_for_storage_assisted_migration(self, host):
        if 'pool_id' not in host['capabilities']:
            LOG.warning(_LW('Failed to get target pool id'))
            return (False, None)

        dst_pool_id = host['capabilities']['pool_id']
        if dst_pool_id is None:
            return (False, None)

        return (True, dst_pool_id)

    def _migrate_volume_with_pool(self, volume, dst_pool_id):
        volume_id = volume['id'].replace('-', '')

        # Get old partition data for delete map
        partition_data = self._extract_all_provider_location(
            volume['provider_location'])

        src_part_id = partition_data['partition_id']

        if src_part_id is None:
            src_part_id = self._get_part_id(volume_id)

        # Create New Partition
        self._create_partition_with_pool(volume, dst_pool_id)

        dst_part_id = self._get_part_id(
            volume_id, pool_id=dst_pool_id)

        if dst_part_id is None:
            msg = _('Fail to get new part id in new pool: %(pool_id)s') % {
                'pool_id': dst_pool_id}
            LOG.error(msg)
            raise exception.InfortrendDriverException(err=msg)

        # Volume Mirror from old partition into new partition
        self._create_replica(
            'Cinder-Migrate', 'part', src_part_id, 'part', dst_part_id,
            'type=mirror')

        self._wait_replica_complete(dst_part_id)

        self._delete_map('part', src_part_id, '-y')
        self._delete_part(src_part_id, '-y')

        model_dict = {
            'system_id': partition_data['system_id'],
            'partition_id': dst_part_id,
        }

        return model_dict

    def _wait_replica_complete(self, part_id):
        start_time = int(time.time())
        timeout = self._replica_timeout

        def _inner():
            check_done = False
            try:
                rc, replica_list = self._show_replica('-l')
                for entry in replica_list:
                    if (entry['Target'] == part_id and
                            self._check_replica_completed(entry)):
                        check_done = True
                        self._delete_replica(entry['Pair-ID'], '-y')
            except Exception:
                check_done = False
                LOG.exception(_LE('Cannot detect replica status.'))

            if check_done:
                raise loopingcall.LoopingCallDone()

            if int(time.time()) - start_time > timeout:
                msg = (_('Wait replica complete timeout'))
                LOG.error(msg)
                raise exception.InfortrendDriverException(err=msg)

        timer = loopingcall.FixedIntervalLoopingCall(_inner)
        timer.start(interval=10).wait()

    def _check_extraspec_value(self, extraspec, validvalues):
        if not extraspec:
            LOG.debug("The given extraspec is None.")
        elif extraspec not in validvalues:
            msg = _("The extraspec: %(extraspec)s is not valid.") % {
                'extraspec': extraspec}
            LOG.error(msg)
            raise exception.InfortrendDriverException(err=msg)

    def _get_enable_specs_on_array(self):
        enable_specs = {}
        rc, license_list = self._show_license()

        for key, value in license_list.items():
            if value['Support']:
                enable_specs[key] = value

        return enable_specs

    def manage_existing_get_size(self, volume, ref):
        """Return size of volume to be managed by manage_existing."""

        if 'source-id' not in ref:
            msg = _('Reference must contain source-id element.')
            LOG.error(msg)
            raise exception.InfortrendAPIException(err=msg)

        source_id = ref['source-id'].replace('-', '')

        part_entry = self._get_latter_volume_dict(source_id)

        rc, map_info = self._show_map('part=%s' % part_entry['ID'])

        if len(map_info) != 0:
            msg = _('The specified volume is mapped to a host.')
            LOG.error(msg)
            raise exception.InfortrendAPIException(err=msg)

        return int(math.ceil(mi_to_gi(float(part_entry['Size']))))

    def manage_existing(self, volume, ref):
        if 'source-id' not in ref:
            msg = _('Reference must contain source-id element.')
            LOG.error(msg)
            raise exception.ManageExistingInvalidReference(
                existing_ref=ref, reason=msg)

        source_id = ref['source-id'].replace('-', '')
        volume_id = volume['id'].replace('-', '')

        part_entry = self._get_latter_volume_dict(source_id)

        self._set_part(part_entry['ID'], 'name=%s' % volume_id)

        LOG.info(_LI('Rename Volume %(volume_id)s done'), {
            'volume_id': volume['id']})

    def _get_specific_volume_dict(self, volume_id):
        ref_dict = {}
        rc, part_list = self._show_part()

        for entry in part_list:
            if entry['Name'] == volume_id:
                ref_dict = entry
                break

        return ref_dict

    def _get_latter_volume_dict(self, volume_id):
        rc, part_list = self._show_part('-l')

        latest_timestamps = 0
        ref_dict = {}

        for entry in part_list:
            if entry['Name'] == volume_id:

                timestamps = self._get_part_timestamps(
                    entry['Creation-time'])

                if timestamps > latest_timestamps:
                    ref_dict = entry
                    latest_timestamps = timestamps

        return ref_dict

    def _get_part_timestamps(self, time_string):
        """Transform 'Sat, Jan 11 22:18:40 2020' into timestamps with sec"""

        first, value = time_string.split(',')
        timestamps = time.mktime(
            time.strptime(value, " %b %d %H:%M:%S %Y"))

        return timestamps

    def retype(self, ctxt, volume, new_type, diff, host):
        """Convert the volume to be of the new type."""

        provisoing_diff = self._diff_between_types(
            volume, new_type, 'provisioning')
        if provisoing_diff:
            new_extraspecs = self._get_extraspecs_dict(new_type['id'])
            new_provisioning = self._get_extraspecs_value(
                new_extraspecs, 'provisioning')
            msg = _("The extraspec: %(provisioning)s is not valid.") % {
                'provisioning': new_provisioning}
            LOG.error(msg)
            raise exception.InfortrendDriverException(err=msg)

        LOG.info(_LI('Retype Volume %(volume_id)s is done'), {
            'volume_id': volume['id']})

    def _diff_between_types(self, volume, new_type, key):
        old_extraspecs = self._get_extraspecs_dict(volume['volume_type_id'])
        new_extraspecs = self._get_extraspecs_dict(new_type['id'])

        old_extraspec = self._get_extraspecs_value(old_extraspecs, key)
        new_extraspec = self._get_extraspecs_value(new_extraspecs, key)

        return new_extraspec != old_extraspec

    def update_migrated_volume(self, ctxt, volume, new_volume):
        """Return model update for migrated volume.
        :param volume: The original volume that was migrated to this backend
        :param new_volume: The migration volume object that was created on
                           this backend as part of the migration process
        :return model_update to update DB with any needed changes
        """
        src_volume_id = volume.get('id')
        dst_volume_id = new_volume.get('id')
        dst_volume_existence = False
        LOG.debug('Update migrated volume: %(dst)s to %(src)s',
                  {'dst': dst_volume_id,
                   'src': src_volume_id})
        if src_volume_id:
            src_volume_id = src_volume_id.replace('-', '')
            dst_volume_id = dst_volume_id.replace('-', '')
            rc, part_list = self._show_part()
            for entry in part_list:
                if entry['Name'] == dst_volume_id:
                    dst_volume_existence = True
            if dst_volume_existence:
                part_id = self._get_part_id(dst_volume_id)
                self._set_part(part_id, 'name=%s' % src_volume_id)
                system_id = self._get_system_id(self.ip)
                model_dict = {
                    'system_id': system_id,
                    'partition_id': part_id
                }
                model_update = {
                    "provider_location":
                        self._concat_provider_location(model_dict)
                }
                return model_update
        LOG.error(_LE('Unable to rename the partition for volume: %s'),
                  src_volume_id)
        return None
