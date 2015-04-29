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

import copy
import re

import mock

from cinder import test
from cinder.tests.unit.test_infortrend_cli import InfortrendCLITestData
from cinder.tests.unit import utils
from cinder.volume.configuration import Configuration
from cinder.volume.drivers.infortrend.eonstor_ds_cli import common_cli
from cinder.volume.drivers.infortrend.eonstor_ds_cli.common_cli import LOG
from cinder.volume.drivers.infortrend import infortrend_exception as exception

SUCCEED = (0, '')
FAKE_ERROR_RETURN = (-1, '')


class InfortrendTestCass(test.TestCase):

    def __init__(self, *args, **kwargs):
        super(InfortrendTestCass, self).__init__(*args, **kwargs)

    def setUp(self):
        super(InfortrendTestCass, self).setUp()
        self.cli_data = InfortrendCLITestData()

        self.configuration = Configuration(None)
        self.configuration.append_config_values = mock.Mock(return_value=0)
        self.configuration.safe_get = self._fake_safe_get

    def _fake_safe_get(self, key):
        return getattr(self.configuration, key)

    def _driver_setup(self, mock_commands, configuration=None):
        if configuration is None:
            configuration = self.configuration
        self.driver = self._get_driver(configuration)

        mock_commands_execute = self._mock_command_execute(mock_commands)
        mock_cli = mock.Mock(side_effect=mock_commands_execute)

        self.driver._execute_command = mock_cli

    def _get_driver(self, conf):
        raise NotImplementedError

    def _mock_command_execute(self, mock_commands):
        def fake_execute_command(cli_type, *args, **kwargs):
            if cli_type in mock_commands.keys():
                if isinstance(mock_commands[cli_type], list):
                    ret = mock_commands[cli_type][0]
                    del mock_commands[cli_type][0]
                    return ret
                elif isinstance(mock_commands[cli_type], tuple):
                    return mock_commands[cli_type]
                else:
                    return mock_commands[cli_type](*args, **kwargs)
            return FAKE_ERROR_RETURN
        return fake_execute_command

    def _mock_show_lv_for_tiering(self, *args, **kwargs):
        if 'tier' in args:
            return self.cli_data.get_test_show_lv_tier_for_tiering()
        else:
            return self.cli_data.get_test_show_lv()

    def _mock_show_lv_for_migrate(self, *args, **kwargs):
        if 'tier' in args:
            return self.cli_data.get_test_show_lv_tier_for_migration()
        else:
            return self.cli_data.get_test_show_lv()

    def _mock_show_lv_4tier(self, *args, **kwargs):
        if 'tier' in args:
            return self.cli_data.get_test_show_lv_4tiers()
        else:
            return self.cli_data.get_test_show_lv()

    def _mock_show_lv(self, *args, **kwargs):
        if 'tier' in args:
            return self.cli_data.get_test_show_lv_tier()
        else:
            return self.cli_data.get_test_show_lv()

    def _mock_thin_provisioning_diff(self, *args, **kwargs):
        if '0' in args:
            return self.cli_data.get_fake_thin_provisioning_no_support()
        elif '1' in args:
            return self.cli_data.get_fake_thin_provisioning_support()

    def _mock_tiering_diff(self, *args, **kwargs):
        if '4' in args:
            return self.cli_data.get_fake_4tiers_support()
        elif '2' in args:
            return self.cli_data.get_fake_2tiers_support()

    def _assert_cli_has_calls(self, expect_cli_cmd):
        self.driver._execute_command.assert_has_calls(expect_cli_cmd)


class InfortrendFCCommonTestCase(InfortrendTestCass):

    def __init__(self, *args, **kwargs):
        super(InfortrendFCCommonTestCase, self).__init__(*args, **kwargs)

    def setUp(self):
        super(InfortrendFCCommonTestCase, self).setUp()

        self.configuration.volume_backend_name = 'infortrend_backend_1'
        self.configuration.san_ip = self.cli_data.fake_manage_port_ip[0]
        self.configuration.san_password = '111111'
        self.configuration.infortrend_provisioning = 'full'
        self.configuration.infortrend_tiering = '0'
        self.configuration.infortrend_pools_name = 'LV-1, LV-2'
        self.configuration.infortrend_slots_a_channels_id = '0,5'
        self.configuration.infortrend_slots_b_channels_id = '0,5'

    def _get_driver(self, conf):
        return common_cli.InfortrendCommon('FC', configuration=conf)

    @mock.patch.object(LOG, 'info', mock.Mock())
    def test_initialize_connection(self):

        test_volume = self.cli_data.test_volume
        test_connector = self.cli_data.test_connector

        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel(),
            'ShowMap': self.cli_data.get_test_show_map(),
            'CreateMap': SUCCEED,
            'ShowWWN': self.cli_data.get_test_show_wwn_with_g_model()
        }
        self._driver_setup(mock_commands)

        properties = self.driver.initialize_connection(
            test_volume, test_connector)

        self.assertDictMatch(properties, self.cli_data.test_fc_properties)

    @mock.patch.object(LOG, 'info', mock.Mock())
    def test_initialize_connection_multipath_with_r_model(self):

        test_volume = self.cli_data.test_volume
        test_connector = copy.deepcopy(self.cli_data.test_connector)
        test_connector['multipath'] = True

        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel_r_model(),
            'ShowMap': self.cli_data.get_test_show_map(),
            'CreateMap': SUCCEED,
            'ShowWWN': self.cli_data.get_test_show_wwn()
        }
        self._driver_setup(mock_commands)

        properties = self.driver.initialize_connection(
            test_volume, test_connector)

        self.assertDictMatch(
            properties, self.cli_data.test_fc_properties_multipath_r_model)

    @mock.patch.object(LOG, 'info', mock.Mock())
    def test_initialize_connection_multipath_with_g_model(self):

        test_volume = self.cli_data.test_volume
        test_connector = copy.deepcopy(self.cli_data.test_connector)
        test_connector['multipath'] = True

        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel(),
            'ShowMap': self.cli_data.get_test_show_map(),
            'CreateMap': SUCCEED,
            'ShowWWN': self.cli_data.get_test_show_wwn_with_g_model()
        }
        self._driver_setup(mock_commands)

        properties = self.driver.initialize_connection(
            test_volume, test_connector)

        self.assertDictMatch(
            properties, self.cli_data.test_fc_properties_multipath_g_model)

    def test_initialize_connection_multipath_with_g_model_single_channel(self):

        test_volume = self.cli_data.test_volume
        test_connector = copy.deepcopy(self.cli_data.test_connector)
        test_connector['multipath'] = True

        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel_single(),
            'ShowMap': self.cli_data.get_test_show_map()
        }
        self._driver_setup(mock_commands)

        ex = self.assertRaises(
            exception.InfortrendDriverException,
            self.driver.initialize_connection,
            test_volume,
            test_connector)
        self.assertTrue(re.match(
            r'.*Can not find the enough channel for mapping.*', ex.msg))

    def test_initialize_connection_with_get_wwn_fail(self):

        test_volume = self.cli_data.test_volume
        test_connector = self.cli_data.test_connector

        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel(),
            'ShowMap': self.cli_data.get_test_show_map(),
            'CreateMap': SUCCEED,
            'ShowWWN': FAKE_ERROR_RETURN
        }
        self._driver_setup(mock_commands)

        ex = self.assertRaises(
            exception.InfortrendCliException,
            self.driver.initialize_connection,
            test_volume,
            test_connector)
        self.assertTrue(re.match(r'.*Failed to get wwn info.*', ex.msg))


class InfortrendiSCSICommonTestCase(InfortrendTestCass):

    def __init__(self, *args, **kwargs):
        super(InfortrendiSCSICommonTestCase, self).__init__(*args, **kwargs)

    def setUp(self):
        super(InfortrendiSCSICommonTestCase, self).setUp()

        self.configuration.volume_backend_name = 'infortrend_backend_1'
        self.configuration.san_ip = self.cli_data.fake_manage_port_ip[0]
        self.configuration.san_password = '111111'
        self.configuration.infortrend_provisioning = 'full'
        self.configuration.infortrend_tiering = '0'
        self.configuration.infortrend_pools_name = 'LV-1, LV-2'
        self.configuration.infortrend_slots_a_channels_id = '1,2,4'
        self.configuration.infortrend_slots_b_channels_id = '1,2,4'

    def _get_driver(self, conf):
        return common_cli.InfortrendCommon('iSCSI', configuration=conf)

    def test_normal_channel(self):

        test_map_dict = {
            'slot_a': {'1': [], '2': [], '4': []},
            'slot_b': {}
        }
        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel()
        }
        self._driver_setup(mock_commands)

        self.driver._init_map_info()

        self.assertDictMatch(self.driver.map_dict, test_map_dict)

    def test_normal_channel_with_multipath(self):

        test_map_dict = {
            'slot_a': {'1': [], '2': [], '4': []},
            'slot_b': {}
        }
        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel()
        }
        self._driver_setup(mock_commands)

        self.driver._init_map_info(multipath=True)

        self.assertDictMatch(self.driver.map_dict, test_map_dict)

    def test_specific_channel(self):

        configuration = copy.copy(self.configuration)
        configuration.infortrend_slots_a_channels_id = '2, 4'

        test_base_logical_channel = 1
        test_map_dict = {
            'slot_a': {'2': [], '4': []},
            'slot_b': {}
        }
        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel()
        }
        self._driver_setup(mock_commands, configuration)

        self.driver._init_map_info()

        self.assertDictMatch(self.driver.map_dict, test_map_dict)
        self.assertEqual(
            self.driver._base_logical_channel, test_base_logical_channel)

    def test_update_mcs_dict(self):

        configuration = copy.copy(self.configuration)
        configuration.infortrend_iscsi_mcs = True

        test_mcs_dict = {
            'slot_a': {'1': ['1', '2'], '2': ['4']},
            'slot_b': {}
        }
        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel_with_mcs()
        }
        self._driver_setup(mock_commands, configuration)

        self.driver._init_map_info()

        self.assertDictMatch(self.driver.mcs_dict, test_mcs_dict)

    def test_mapping_info_with_mcs(self):

        configuration = copy.copy(self.configuration)
        configuration.infortrend_iscsi_mcs = True

        fake_mcs_dict = {
            'slot_a': {'0': ['1', '2'], '2': ['4']},
            'slot_b': {}
        }
        lun_list = list(range(0, 127))
        fake_map_dict = {
            'slot_a': {'1': lun_list[2:], '2': lun_list[:], '4': lun_list[1:]},
            'slot_b': {}
        }

        test_map_chl = {
            'slot_a': ['1', '2']
        }
        test_map_lun = ['2']
        test_mcs_id = '0'
        self.driver = self._get_driver(configuration)
        self.driver.mcs_dict = fake_mcs_dict
        self.driver.map_dict = fake_map_dict

        map_chl, map_lun, mcs_id = \
            self.driver._get_mapping_info_with_multi_lun_on_iscsi_mcs()

        self.assertDictMatch(map_chl, test_map_chl)
        self.assertEqual(map_lun, test_map_lun)
        self.assertEqual(mcs_id, test_mcs_id)

    def test_mapping_info_with_mcs_multi_group(self):

        configuration = copy.copy(self.configuration)
        configuration.infortrend_iscsi_mcs = True

        fake_mcs_dict = {
            'slot_a': {'0': ['1', '2'], '1': ['3', '4'], '2': ['5']},
            'slot_b': {}
        }
        lun_list = list(range(0, 127))
        fake_map_dict = {
            'slot_a': {
                '1': lun_list[2:],
                '2': lun_list[:],
                '3': lun_list[:],
                '4': lun_list[1:],
                '5': lun_list[:]
            },
            'slot_b': {}
        }

        test_map_chl = {
            'slot_a': ['3', '4']
        }
        test_map_lun = ['1']
        test_mcs_id = '1'
        self.driver = self._get_driver(configuration)
        self.driver.mcs_dict = fake_mcs_dict
        self.driver.map_dict = fake_map_dict

        map_chl, map_lun, mcs_id = \
            self.driver._get_mapping_info_with_multi_lun_on_iscsi_mcs()

        self.assertDictMatch(map_chl, test_map_chl)
        self.assertEqual(map_lun, test_map_lun)
        self.assertEqual(mcs_id, test_mcs_id)

    def test_specific_channel_with_multipath(self):

        configuration = copy.copy(self.configuration)
        configuration.infortrend_slots_a_channels_id = '1,2'

        test_map_dict = {
            'slot_a': {'1': [], '2': []},
            'slot_b': {}
        }
        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel()
        }
        self._driver_setup(mock_commands, configuration)

        self.driver._init_map_info(multipath=True)

        self.assertDictMatch(self.driver.map_dict, test_map_dict)

    def test_specific_channel_with_multipath_r_model(self):

        configuration = copy.copy(self.configuration)
        configuration.infortrend_slots_a_channels_id = '1,2'
        configuration.infortrend_slots_b_channels_id = '1'

        test_map_dict = {
            'slot_a': {'1': [], '2': []},
            'slot_b': {'1': []}
        }
        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel_r_model()
        }
        self._driver_setup(mock_commands, configuration)

        self.driver._init_map_info(multipath=True)

        self.assertDictMatch(self.driver.map_dict, test_map_dict)

    @mock.patch.object(LOG, 'info')
    def test_create_volume(self, log_info):

        test_volume = self.cli_data.test_volume
        test_model_update = {
            'provider_location': 'system_id^%s@partition_id^%s' % (
                int(self.cli_data.fake_system_id[0], 16),
                self.cli_data.fake_partition_id[0])
        }

        mock_commands = {
            'CreatePartition': SUCCEED,
            'ShowPartition': self.cli_data.get_test_show_partition(),
            'ShowDevice': self.cli_data.get_test_show_device(),
            'ShowLV': self._mock_show_lv
        }
        self._driver_setup(mock_commands)

        model_update = self.driver.create_volume(test_volume)

        self.assertDictMatch(model_update, test_model_update)
        log_info.assert_called_once_with(
            'Create Volume %s done', test_volume['id'].replace('-', ''))

    @mock.patch.object(LOG, 'info', mock.Mock())
    def test_create_volume_with_create_fail(self):
        test_volume = self.cli_data.test_volume

        mock_commands = {
            'CreatePartition': FAKE_ERROR_RETURN,
            'ShowPartition': self.cli_data.get_test_show_partition(),
            'ShowDevice': self.cli_data.get_test_show_device(),
            'ShowLV': self._mock_show_lv
        }
        self._driver_setup(mock_commands)

        ex = self.assertRaises(
            exception.InfortrendCliException,
            self.driver.create_volume,
            test_volume)
        self.assertTrue(re.match(
            r'.*Failed to create partition.*', ex.msg))

    @mock.patch.object(LOG, 'info')
    def test_delete_volume(self, log_info):

        test_volume = self.cli_data.test_volume
        test_partition_id = self.cli_data.fake_partition_id[0]
        test_snapshot_id = self.cli_data.fake_snapshot_id
        test_pair_id = self.cli_data.fake_pair_id

        mock_commands = {
            'ShowPartition':
                self.cli_data.get_test_show_partition_detail_for_map(
                    test_partition_id),
            'ShowReplica': self.cli_data.get_test_show_replica_detail(),
            'DeleteReplica': SUCCEED,
            'ShowSnapshot': self.cli_data.get_test_show_snapshot(),
            'DeleteSnapshot': SUCCEED,
            'ShowMap': self.cli_data.get_test_show_map(),
            'DeleteMap': SUCCEED,
            'DeletePartition': SUCCEED
        }
        self._driver_setup(mock_commands)

        self.driver.delete_volume(test_volume)

        expect_cli_cmd = [
            mock.call('ShowPartition', '-l'),
            mock.call('ShowReplica', '-l'),
            mock.call('DeleteReplica', test_pair_id[0], '-y'),
            mock.call('ShowSnapshot', 'part=%s' % test_partition_id),
            mock.call('DeleteSnapshot', test_snapshot_id[0], '-y'),
            mock.call('DeleteSnapshot', test_snapshot_id[1], '-y'),
            mock.call('ShowMap', 'part=%s' % test_partition_id),
            mock.call('DeleteMap', 'part', test_partition_id, '-y'),
            mock.call('DeletePartition', test_partition_id, '-y')
        ]
        self._assert_cli_has_calls(expect_cli_cmd)

        log_info.assert_called_once_with(
            'Delete Volume %s done', test_volume['id'].replace('-', ''))

    @mock.patch.object(LOG, 'warning', mock.Mock())
    def test_delete_volume_with_sync_pair(self):

        test_volume = self.cli_data.test_volume
        test_partition_id = self.cli_data.fake_partition_id[0]

        mock_commands = {
            'ShowPartition':
                self.cli_data.get_test_show_partition_detail_for_map(
                    test_partition_id),
            'ShowReplica':
                self.cli_data.get_test_show_replica_detail_for_sync_pair()
        }
        self._driver_setup(mock_commands)

        ex = self.assertRaises(
            exception.InfortrendDriverException,
            self.driver.delete_volume,
            test_volume)
        self.assertTrue(re.match(
            r'.*because it has pair.*', ex.msg))

    def test_delete_volume_with_delete_fail(self):

        test_volume = self.cli_data.test_volume
        test_partition_id = self.cli_data.fake_partition_id[0]

        mock_commands = {
            'ShowPartition':
                self.cli_data.get_test_show_partition_detail_for_map(
                    test_partition_id),
            'ShowReplica': self.cli_data.get_test_show_replica_detail(),
            'DeleteReplica': SUCCEED,
            'ShowSnapshot': self.cli_data.get_test_show_snapshot(),
            'DeleteSnapshot': SUCCEED,
            'ShowMap': self.cli_data.get_test_show_map(),
            'DeleteMap': SUCCEED,
            'DeletePartition': FAKE_ERROR_RETURN
        }
        self._driver_setup(mock_commands)

        ex = self.assertRaises(
            exception.InfortrendCliException,
            self.driver.delete_volume,
            test_volume)
        self.assertTrue(re.match(
            r'.*Failed to delete partition.*', ex.msg))

    @mock.patch.object(LOG, 'warning')
    def test_delete_volume_with_partiton_not_found(self, log_warning):

        test_volume = self.cli_data.test_volume
        test_volume_id = test_volume['id'].replace('-', '')

        mock_commands = {
            'ShowPartition': self.cli_data.get_test_show_empty_list()
        }
        self._driver_setup(mock_commands)

        self.driver.delete_volume(test_volume)

        log_warning.assert_called_once_with(
            'Volume %s already delete', test_volume_id)

    @mock.patch.object(LOG, 'info')
    def test_delete_volume_without_provider(self, log_info):

        test_system_id = self.cli_data.fake_system_id[0]
        test_volume = copy.deepcopy(self.cli_data.test_volume)
        test_volume['provider_location'] = 'system_id^%s@partition_id^%s' % (
            int(test_system_id, 16), 'None')
        test_volume_id = test_volume['id'].replace('-', '')
        test_partition_id = self.cli_data.fake_partition_id[0]

        mock_commands = {
            'ShowPartition':
                self.cli_data.get_test_show_partition_detail_for_map(
                    test_partition_id),
            'ShowReplica': self.cli_data.get_test_show_replica_detail(),
            'DeleteReplica': SUCCEED,
            'ShowSnapshot': self.cli_data.get_test_show_snapshot(),
            'DeleteSnapshot': SUCCEED,
            'ShowMap': self.cli_data.get_test_show_map(),
            'DeleteMap': SUCCEED,
            'DeletePartition': SUCCEED
        }
        self._driver_setup(mock_commands)

        self.driver.delete_volume(test_volume)

        log_info.assert_called_once_with(
            'Delete Volume %s done', test_volume_id)

    @mock.patch('cinder.openstack.common.loopingcall.FixedIntervalLoopingCall',
                new=utils.ZeroIntervalLoopingCall)
    @mock.patch.object(LOG, 'info')
    def test_create_cloned_volume(self, log_info):

        fake_partition_id = self.cli_data.fake_partition_id[0]
        fake_snapshot_id = self.cli_data.fake_snapshot_id[0]
        test_dst_volume = self.cli_data.test_dst_volume
        test_dst_volume_id = test_dst_volume['id'].replace('-', '')
        test_src_volume = self.cli_data.test_volume
        test_dst_part_id = self.cli_data.fake_partition_id[1]
        test_model_update = {
            'provider_location': 'system_id^%s@partition_id^%s' % (
                int(self.cli_data.fake_system_id[0], 16),
                self.cli_data.fake_partition_id[1])
        }
        # todo: change provider_location value
        mock_commands = {
            'CreateSnapshot': SUCCEED,
            'ShowSnapshot': self.cli_data.get_test_show_snapshot(
                partition_id=fake_partition_id,
                snapshot_id=fake_snapshot_id),
            'CreatePartition': SUCCEED,
            'ShowPartition': self.cli_data.get_test_show_partition(),
            'ShowDevice': self.cli_data.get_test_show_device(),
            'CreateReplica': SUCCEED,
            'ShowLV': self._mock_show_lv,
            'ShowReplica':
                self.cli_data.get_test_show_replica_detail_for_migrate(
                    fake_snapshot_id, test_dst_part_id, test_dst_volume_id),
            'DeleteReplica': SUCCEED
        }
        self._driver_setup(mock_commands)

        model_update = self.driver.create_cloned_volume(
            test_dst_volume, test_src_volume)

        self.assertDictMatch(model_update, test_model_update)
        log_info.assert_called_once_with(
            'Create Cloned Volume %s done', test_dst_volume['id'])

    @mock.patch.object(LOG, 'info', mock.Mock())
    def test_create_cloned_volume_with_create_replica_fail(self):

        fake_partition_id = self.cli_data.fake_partition_id[0]
        fake_snapshot_id = self.cli_data.fake_snapshot_id[0]
        test_dst_volume = self.cli_data.test_dst_volume
        test_src_volume = self.cli_data.test_volume

        # todo: change provider_location value
        mock_commands = {
            'CreateSnapshot': SUCCEED,
            'ShowSnapshot': self.cli_data.get_test_show_snapshot(
                partition_id=fake_partition_id,
                snapshot_id=fake_snapshot_id),
            'CreatePartition': SUCCEED,
            'ShowPartition': self.cli_data.get_test_show_partition(),
            'ShowDevice': self.cli_data.get_test_show_device(),
            'CreateReplica': FAKE_ERROR_RETURN,
            'ShowLV': self._mock_show_lv
        }
        self._driver_setup(mock_commands)

        ex = self.assertRaises(
            exception.InfortrendCliException,
            self.driver.create_cloned_volume,
            test_dst_volume,
            test_src_volume)
        self.assertTrue(re.match(r'.*Failed to create replica.*', ex.msg))

    def test_create_export(self):

        test_volume = self.cli_data.test_volume
        test_model_update = {
            'provider_location': test_volume['provider_location']
        }
        self.driver = self._get_driver(self.configuration)

        model_update = self.driver.create_export(None, test_volume)

        self.assertDictMatch(model_update, test_model_update)

    def test_get_volume_stats(self):

        test_volume_states = self.cli_data.test_volume_states

        mock_commands = {
            'ShowLicense': self.cli_data.get_test_show_license(),
            'ShowLV': self.cli_data.get_test_show_lv()
        }
        self._driver_setup(mock_commands)
        self.driver.VERSION = '99.99'

        volume_states = self.driver.get_volume_stats(True)

        self.assertDictMatch(volume_states, test_volume_states)

    def test_get_volume_stats_fail(self):

        mock_commands = {
            'ShowLicense': self.cli_data.get_test_show_license(),
            'ShowLV': FAKE_ERROR_RETURN
        }
        self._driver_setup(mock_commands)

        ex = self.assertRaises(
            exception.InfortrendCliException,
            self.driver.get_volume_stats)
        self.assertTrue(re.match(r'.*Failed to get lv info.*', ex.msg))

    @mock.patch.object(LOG, 'info', mock.Mock())
    def test_create_snapshot(self):

        fake_partition_id = self.cli_data.fake_partition_id[0]
        fake_snapshot_id = self.cli_data.fake_snapshot_id[0]

        mock_commands = {
            'CreateSnapshot': SUCCEED,
            'ShowSnapshot': self.cli_data.get_test_show_snapshot(
                partition_id=fake_partition_id,
                snapshot_id=fake_snapshot_id),
            'ShowPartition': self.cli_data.get_test_show_partition()
        }
        self._driver_setup(mock_commands)

        model_update = self.driver.create_snapshot(self.cli_data.test_snapshot)

        assert(model_update['provider_location'] == fake_snapshot_id)

    @mock.patch.object(LOG, 'info', mock.Mock())
    def test_create_snapshot_without_partition_id(self):

        fake_partition_id = self.cli_data.fake_partition_id[0]
        fake_snapshot_id = self.cli_data.fake_snapshot_id[0]
        test_snapshot = self.cli_data.test_snapshot

        mock_commands = {
            'CreateSnapshot': SUCCEED,
            'ShowSnapshot': self.cli_data.get_test_show_snapshot(
                partition_id=fake_partition_id,
                snapshot_id=fake_snapshot_id),
            'ShowPartition': FAKE_ERROR_RETURN
        }
        self._driver_setup(mock_commands)

        ex = self.assertRaises(
            exception.InfortrendCliException,
            self.driver.create_snapshot,
            test_snapshot)
        self.assertTrue(re.match(r'.*Failed to get partition info.*', ex.msg))

    def test_create_snapshot_with_create_fail(self):

        fake_partition_id = self.cli_data.fake_partition_id[0]
        fake_snapshot_id = self.cli_data.fake_snapshot_id[0]
        test_snapshot = self.cli_data.test_snapshot

        mock_commands = {
            'CreateSnapshot': FAKE_ERROR_RETURN,
            'ShowSnapshot': self.cli_data.get_test_show_snapshot(
                partition_id=fake_partition_id,
                snapshot_id=fake_snapshot_id),
            'ShowPartition': self.cli_data.get_test_show_partition()
        }
        self._driver_setup(mock_commands)

        ex = self.assertRaises(
            exception.InfortrendCliException,
            self.driver.create_snapshot,
            test_snapshot)
        self.assertTrue(re.match(r'.*Failed to create snapshot.*', ex.msg))

    def test_create_snapshot_with_show_fail(self):

        test_snapshot = self.cli_data.test_snapshot

        mock_commands = {
            'CreateSnapshot': SUCCEED,
            'ShowSnapshot': FAKE_ERROR_RETURN,
            'ShowPartition': self.cli_data.get_test_show_partition()
        }
        self._driver_setup(mock_commands)

        ex = self.assertRaises(
            exception.InfortrendCliException,
            self.driver.create_snapshot,
            test_snapshot)
        self.assertTrue(re.match(r'.*Failed to get snapshot info.*', ex.msg))

    @mock.patch.object(LOG, 'info')
    def test_delete_snapshot(self, log_info):

        test_snapshot = self.cli_data.test_snapshot

        mock_commands = {
            'ShowReplica': self.cli_data.get_test_show_replica_detail(),
            'DeleteSnapshot': SUCCEED
        }
        self._driver_setup(mock_commands)

        self.driver.delete_snapshot(test_snapshot)

        log_info.assert_called_once_with(
            'Delete Snapshot %s done', test_snapshot['id'].replace('-', ''))

    def test_delete_snapshot_without_provider_location(self):

        test_snapshot = self.cli_data.test_snapshot

        self.driver = self._get_driver(self.configuration)
        self.driver._get_snapshot_id = mock.Mock(return_value=None)

        ex = self.assertRaises(
            exception.InfortrendAPIException,
            self.driver.delete_snapshot,
            test_snapshot)
        self.assertTrue(re.match(r'.*Failed to get Snapshot ID.*', ex.msg))

    def test_delete_snapshot_with_fail(self):

        test_snapshot = self.cli_data.test_snapshot

        mock_commands = {
            'ShowReplica': self.cli_data.get_test_show_replica_detail(),
            'DeleteSnapshot': FAKE_ERROR_RETURN
        }
        self._driver_setup(mock_commands)

        ex = self.assertRaises(
            exception.InfortrendCliException,
            self.driver.delete_snapshot,
            test_snapshot)
        self.assertTrue(re.match(r'.*Failed to delete snapshot.*', ex.msg))

    @mock.patch.object(LOG, 'warning', mock.Mock())
    def test_delete_snapshot_with_sync_pair(self):

        test_snapshot = self.cli_data.test_snapshot

        mock_commands = {
            'ShowReplica':
                self.cli_data.get_test_show_replica_detail_for_si_sync_pair(),
            'DeleteSnapshot': FAKE_ERROR_RETURN
        }
        self._driver_setup(mock_commands)

        ex = self.assertRaises(
            exception.InfortrendDriverException,
            self.driver.delete_snapshot,
            test_snapshot)
        self.assertTrue(re.match(r'.*because it has pair.*', ex.msg))

    @mock.patch('cinder.openstack.common.loopingcall.FixedIntervalLoopingCall',
                new=utils.ZeroIntervalLoopingCall)
    @mock.patch.object(LOG, 'info')
    def test_create_volume_from_snapshot(self, log_info):

        test_snapshot = self.cli_data.test_snapshot
        test_snapshot_id = self.cli_data.fake_snapshot_id[0]
        test_dst_volume = self.cli_data.test_dst_volume
        test_dst_volume_id = test_dst_volume['id'].replace('-', '')
        test_dst_part_id = self.cli_data.fake_partition_id[1]
        test_model_update = {
            'provider_location': 'system_id^%s@partition_id^%s' % (
                int(self.cli_data.fake_system_id[0], 16),
                self.cli_data.fake_partition_id[1])
        }
        mock_commands = {
            'CreatePartition': SUCCEED,
            'ShowPartition': self.cli_data.get_test_show_partition(),
            'ShowDevice': self.cli_data.get_test_show_device(),
            'CreateReplica': SUCCEED,
            'ShowLV': self._mock_show_lv,
            'ShowReplica':
                self.cli_data.get_test_show_replica_detail_for_migrate(
                    test_snapshot_id, test_dst_part_id, test_dst_volume_id),
            'DeleteReplica': SUCCEED
        }
        self._driver_setup(mock_commands)

        model_update = self.driver.create_volume_from_snapshot(
            test_dst_volume, test_snapshot)

        self.assertDictMatch(model_update, test_model_update)
        log_info.assert_called_once_with(
            'Create Volume %(volume_id)s form snapshot %(snapshot_id)s done', {
                'volume_id': test_dst_volume['id'],
                'snapshot_id': test_snapshot['id']})

    def test_create_volume_from_snapshot_without_provider_location(
            self):

        test_snapshot = self.cli_data.test_snapshot
        test_dst_volume = self.cli_data.test_dst_volume

        self.driver = self._get_driver(self.configuration)
        self.driver._get_snapshot_id = mock.Mock(return_value=None)

        ex = self.assertRaises(
            exception.InfortrendAPIException,
            self.driver.create_volume_from_snapshot,
            test_dst_volume,
            test_snapshot)
        self.assertTrue(re.match(r'.*Failed to get Snapshot ID.*', ex.msg))

    @mock.patch.object(LOG, 'info', mock.Mock())
    def test_initialize_connection(self):

        test_volume = self.cli_data.test_volume
        test_partition_id = self.cli_data.fake_partition_id[0]
        test_connector = copy.deepcopy(self.cli_data.test_connector)
        test_iscsi_properties = self.cli_data.test_iscsi_properties
        test_target_protal = [test_iscsi_properties['data']['target_portal']]
        test_target_iqn = [test_iscsi_properties['data']['target_iqn']]

        test_connector['multipath'] = False

        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel(),
            'ShowMap': self.cli_data.get_test_show_map(),
            'ShowIQN': self.cli_data.get_test_show_iqn(),
            'CreateMap': SUCCEED,
            'ShowNet': self.cli_data.get_test_show_net(),
            'ExecuteCommand': self.cli_data.get_fake_discovery(
                test_target_iqn, test_target_protal)
        }
        self._driver_setup(mock_commands)

        properties = self.driver.initialize_connection(
            test_volume, test_connector)

        self.assertDictMatch(properties, test_iscsi_properties)

        expect_cli_cmd = [
            mock.call('CreateMap', 'part', test_partition_id, '2', '0', '0',
                      'iqn=%s' % test_connector['initiator'])
        ]
        self._assert_cli_has_calls(expect_cli_cmd)

    @mock.patch.object(LOG, 'info', mock.Mock())
    def test_initialize_connection_with_iqn_not_exist(self):

        test_volume = self.cli_data.test_volume
        test_partition_id = self.cli_data.fake_partition_id[0]
        test_initiator = copy.deepcopy(self.cli_data.fake_initiator_iqn[1])
        test_connector = copy.deepcopy(self.cli_data.test_connector)
        test_iscsi_properties = self.cli_data.test_iscsi_properties
        test_target_protal = [test_iscsi_properties['data']['target_portal']]
        test_target_iqn = [test_iscsi_properties['data']['target_iqn']]

        test_connector['multipath'] = False
        test_connector['initiator'] = test_initiator

        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel(),
            'ShowMap': self.cli_data.get_test_show_map(),
            'ShowIQN': self.cli_data.get_test_show_iqn(),
            'CreateIQN': SUCCEED,
            'CreateMap': SUCCEED,
            'ShowNet': self.cli_data.get_test_show_net(),
            'ExecuteCommand': self.cli_data.get_fake_discovery(
                test_target_iqn, test_target_protal)
        }
        self._driver_setup(mock_commands)

        properties = self.driver.initialize_connection(
            test_volume, test_connector)

        self.assertDictMatch(properties, test_iscsi_properties)

        expect_cli_cmd = [
            mock.call('CreateIQN', test_initiator, test_initiator[-16:]),
            mock.call('CreateMap', 'part', test_partition_id, '2', '0', '0',
                      'iqn=%s' % test_connector['initiator'])
        ]
        self._assert_cli_has_calls(expect_cli_cmd)

    @mock.patch.object(LOG, 'info', mock.Mock())
    def test_initialize_connection_with_empty_map(self):

        test_volume = self.cli_data.test_volume
        test_connector = copy.deepcopy(self.cli_data.test_connector)
        test_iscsi_properties = self.cli_data.test_iscsi_properties_empty_map
        test_target_protal = [test_iscsi_properties['data']['target_portal']]
        test_target_iqn = [test_iscsi_properties['data']['target_iqn']]

        test_connector['multipath'] = False

        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel(),
            'ShowMap': self.cli_data.get_test_show_empty_list(),
            'ShowIQN': self.cli_data.get_test_show_iqn(),
            'CreateMap': SUCCEED,
            'ShowNet': self.cli_data.get_test_show_net(),
            'ExecuteCommand': self.cli_data.get_fake_discovery(
                test_target_iqn, test_target_protal)
        }
        self._driver_setup(mock_commands)

        properties = self.driver.initialize_connection(
            test_volume, test_connector)

        self.assertDictMatch(
            properties, self.cli_data.test_iscsi_properties_empty_map)

    def test_initialize_connection_with_create_map_fail(self):

        test_volume = self.cli_data.test_volume
        test_connector = self.cli_data.test_connector

        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel_r_model(),
            'ShowMap': self.cli_data.get_test_show_map(),
            'ShowIQN': self.cli_data.get_test_show_iqn(),
            'CreateMap': FAKE_ERROR_RETURN,
            'ShowNet': SUCCEED
        }
        self._driver_setup(mock_commands)

        ex = self.assertRaises(
            exception.InfortrendCliException,
            self.driver.initialize_connection,
            test_volume,
            test_connector)
        self.assertTrue(re.match(r'.*Failed to create map.*', ex.msg))

    def test_initialize_connection_with_get_ip_fail(self):

        test_volume = self.cli_data.test_volume
        test_connector = self.cli_data.test_connector

        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel(),
            'ShowMap': self.cli_data.get_test_show_map(),
            'ShowIQN': self.cli_data.get_test_show_iqn(),
            'CreateMap': SUCCEED,
            'ShowNet': FAKE_ERROR_RETURN
        }
        self._driver_setup(mock_commands)

        ex = self.assertRaises(
            exception.InfortrendCliException,
            self.driver.initialize_connection,
            test_volume,
            test_connector)

        self.assertTrue(re.match(r'.*Failed to get network info.*', ex.msg))

    @mock.patch.object(LOG, 'info', mock.Mock())
    def test_initialize_connection_multipath_with_r_model(self):

        test_volume = self.cli_data.test_volume
        test_connector = copy.deepcopy(self.cli_data.test_connector)
        test_iscsi_properties = \
            self.cli_data.test_iscsi_properties_multipath_r_model
        test_target_protals = test_iscsi_properties['data']['target_portals']
        test_target_iqns = test_iscsi_properties['data']['target_iqns']

        test_connector['multipath'] = True

        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel_r_model(),
            'ShowMap': self.cli_data.get_test_show_map(),
            'ShowIQN': self.cli_data.get_test_show_iqn(),
            'CreateMap': SUCCEED,
            'ShowNet': self.cli_data.get_test_show_net(),
            'ExecuteCommand': self.cli_data.get_fake_discovery(
                test_target_iqns, test_target_protals)
        }
        self._driver_setup(mock_commands)

        properties = self.driver.initialize_connection(
            test_volume, test_connector)

        self.assertDictMatch(
            properties, self.cli_data.test_iscsi_properties_multipath_r_model)

    @mock.patch.object(LOG, 'info', mock.Mock())
    def test_initialize_connection_multipath_with_g_model(self):

        test_volume = self.cli_data.test_volume
        test_connector = copy.deepcopy(self.cli_data.test_connector)
        test_iscsi_properties = \
            self.cli_data.test_iscsi_properties_multipath_g_model
        test_target_protals = test_iscsi_properties['data']['target_portals']
        test_target_iqns = test_iscsi_properties['data']['target_iqns']

        test_connector['multipath'] = True

        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel(),
            'ShowMap': self.cli_data.get_test_show_map(),
            'ShowIQN': self.cli_data.get_test_show_iqn(),
            'CreateMap': SUCCEED,
            'ShowNet': self.cli_data.get_test_show_net(),
            'ExecuteCommand': self.cli_data.get_fake_discovery(
                test_target_iqns, test_target_protals)
        }
        self._driver_setup(mock_commands)

        properties = self.driver.initialize_connection(
            test_volume, test_connector)

        self.assertDictMatch(
            properties, self.cli_data.test_iscsi_properties_multipath_g_model)

    @mock.patch.object(LOG, 'info', mock.Mock())
    def test_initialize_connection_with_mcs(self):

        configuration = copy.copy(self.configuration)
        configuration.infortrend_iscsi_mcs = True

        test_volume = self.cli_data.test_volume
        test_partition_id = self.cli_data.fake_partition_id[0]
        test_connector = copy.deepcopy(self.cli_data.test_connector)
        test_iscsi_properties = self.cli_data.test_iscsi_properties_with_mcs
        test_target_protal = [test_iscsi_properties['data']['target_portal']]
        test_target_iqn = [test_iscsi_properties['data']['target_iqn']]

        test_connector['multipath'] = False

        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel_with_mcs(),
            'ShowMap': self.cli_data.get_test_show_map(),
            'ShowIQN': self.cli_data.get_test_show_iqn(),
            'CreateMap': SUCCEED,
            'ShowNet': self.cli_data.get_test_show_net(),
            'ExecuteCommand': self.cli_data.get_fake_discovery(
                test_target_iqn, test_target_protal)
        }
        self._driver_setup(mock_commands, configuration)

        properties = self.driver.initialize_connection(
            test_volume, test_connector)

        self.assertDictMatch(properties, test_iscsi_properties)

        expect_cli_cmd = [
            mock.call('CreateMap', 'part', test_partition_id, '1', '0', '2',
                      'iqn=%s' % test_connector['initiator'])
        ]
        self._assert_cli_has_calls(expect_cli_cmd)

    @mock.patch.object(LOG, 'info', mock.Mock())
    def test_extend_volume(self):

        test_volume = self.cli_data.test_volume
        test_partition_id = self.cli_data.fake_partition_id[0]
        test_new_size = 10
        test_expand_size = test_new_size - test_volume['size']

        mock_commands = {
            'SetPartition': SUCCEED
        }
        self._driver_setup(mock_commands)

        self.driver.extend_volume(test_volume, test_new_size)

        expect_cli_cmd = [
            mock.call('SetPartition', 'expand', test_partition_id,
                      'size=%sGB' % test_expand_size)
        ]
        self._assert_cli_has_calls(expect_cli_cmd)

    @mock.patch.object(LOG, 'info', mock.Mock())
    def test_extend_volume_mb(self):

        test_volume = self.cli_data.test_volume
        test_partition_id = self.cli_data.fake_partition_id[0]
        test_new_size = 5.5
        test_expand_size = round((test_new_size - test_volume['size']) * 1024)

        mock_commands = {
            'SetPartition': SUCCEED
        }
        self._driver_setup(mock_commands)

        self.driver.extend_volume(test_volume, test_new_size)

        expect_cli_cmd = [
            mock.call('SetPartition', 'expand', test_partition_id,
                      'size=%sMB' % test_expand_size)
        ]
        self._assert_cli_has_calls(expect_cli_cmd)

    def test_extend_volume_fail(self):

        test_volume = self.cli_data.test_volume
        test_new_size = 10

        mock_commands = {
            'SetPartition': FAKE_ERROR_RETURN
        }
        self._driver_setup(mock_commands)

        ex = self.assertRaises(
            exception.InfortrendCliException,
            self.driver.extend_volume,
            test_volume,
            test_new_size)

        self.assertTrue(re.match(r'.*Failed to set partition.*', ex.msg))

    @mock.patch.object(LOG, 'info', mock.Mock())
    def test_terminate_connection(self):

        test_volume = self.cli_data.test_volume
        test_partition_id = self.cli_data.fake_partition_id[0]
        test_connector = self.cli_data.test_connector

        mock_commands = {
            'DeleteMap': SUCCEED,
            'DeleteIQN': SUCCEED,
            'ShowMap': self.cli_data.get_test_show_map()
        }
        self._driver_setup(mock_commands)

        self.driver.terminate_connection(test_volume, test_connector)

        expect_cli_cmd = [
            mock.call('DeleteMap', 'part', test_partition_id, '-y'),
            mock.call('DeleteIQN', test_connector['initiator'][-16:]),
        ]
        self._assert_cli_has_calls(expect_cli_cmd)

    def test_terminate_connection_fail(self):

        test_volume = self.cli_data.test_volume
        test_connector = self.cli_data.test_connector

        mock_commands = {
            'DeleteMap': FAKE_ERROR_RETURN
        }
        self._driver_setup(mock_commands)

        ex = self.assertRaises(
            exception.InfortrendCliException,
            self.driver.terminate_connection,
            test_volume,
            test_connector)

        self.assertTrue(re.match(r'.*Failed to delete map.*', ex.msg))

    @mock.patch('cinder.openstack.common.loopingcall.FixedIntervalLoopingCall',
                new=utils.ZeroIntervalLoopingCall)
    def test_migrate_volume(self):

        test_host = copy.deepcopy(self.cli_data.test_migrate_func_host)
        fake_pool = copy.deepcopy(self.cli_data.fake_pool)
        test_volume = self.cli_data.test_volume
        test_volume_id = test_volume['id'].replace('-', '')
        test_src_part_id = self.cli_data.fake_partition_id[0]
        test_dst_part_id = self.cli_data.fake_partition_id[2]
        test_pair_id = self.cli_data.fake_pair_id[0]
        test_model_update = {
            'provider_location': 'system_id^%s@partition_id^%s' % (
                int(self.cli_data.fake_system_id[0], 16),
                test_dst_part_id)
        }

        mock_commands = {
            'CreatePartition': SUCCEED,
            'ShowPartition': self.cli_data.get_test_show_partition(
                test_volume['id'].replace('-', ''), fake_pool['pool_id']),
            'CreateReplica': SUCCEED,
            'ShowLV': self._mock_show_lv_for_migrate,
            'ShowReplica':
                self.cli_data.get_test_show_replica_detail_for_migrate(
                    test_src_part_id, test_dst_part_id, test_volume_id),
            'DeleteReplica': SUCCEED,
            'DeleteMap': SUCCEED,
            'DeletePartition': SUCCEED
        }
        self._driver_setup(mock_commands)

        rc, model_update = self.driver.migrate_volume(test_volume, test_host)

        expect_cli_cmd = [
            mock.call('CreatePartition',
                      fake_pool['pool_id'],
                      test_volume['id'].replace('-', ''),
                      'size=%s' % (test_volume['size'] * 1024),
                      ''),
            mock.call('ShowPartition'),
            mock.call('CreateReplica',
                      'Cinder-Migrate',
                      'part', test_src_part_id,
                      'part', test_dst_part_id,
                      'type=mirror'),
            mock.call('ShowReplica', '-l'),
            mock.call('DeleteReplica', test_pair_id, '-y'),
            mock.call('DeleteMap', 'part', test_src_part_id, '-y'),
            mock.call('DeletePartition', test_src_part_id, '-y')
        ]
        self._assert_cli_has_calls(expect_cli_cmd)
        self.assertTrue(rc)
        self.assertDictMatch(model_update, test_model_update)

    @mock.patch.object(LOG, 'warning')
    def test_migrate_volume_with_invalid_storage(self, log_warning):

        fake_host = self.cli_data.fake_host
        test_volume = self.cli_data.test_volume

        mock_commands = {
            'ShowLV': self._mock_show_lv_for_migrate
        }
        self._driver_setup(mock_commands)

        rc, model_update = self.driver.migrate_volume(test_volume, fake_host)

        self.assertFalse(rc)
        self.assertTrue(model_update is None)
        log_warning.assert_called_once_with(
            'Failed to get target pool id')

    def test_migrate_volume_with_get_part_id_fail(self):

        test_host = copy.deepcopy(self.cli_data.test_migrate_host)
        test_volume = self.cli_data.test_volume

        mock_commands = {
            'CreatePartition': SUCCEED,
            'ShowPartition': self.cli_data.get_test_show_partition(),
            'DeleteMap': SUCCEED,
            'CreateReplica': SUCCEED,
            'CreateMap': SUCCEED,
            'ShowLV': self._mock_show_lv_for_migrate
        }
        self._driver_setup(mock_commands)

        ex = self.assertRaises(
            exception.InfortrendDriverException,
            self.driver.migrate_volume,
            test_volume,
            test_host)

        self.assertTrue(re.match(
            r'.*Fail to get new part id in new pool.*', ex.msg))

    def test_migrate_volume_with_create_replica_fail(self):

        test_host = copy.deepcopy(self.cli_data.test_migrate_host)
        fake_pool = copy.deepcopy(self.cli_data.fake_pool)
        test_volume = self.cli_data.test_volume

        mock_commands = {
            'CreatePartition': SUCCEED,
            'ShowPartition': self.cli_data.get_test_show_partition(
                test_volume['id'].replace('-', ''), fake_pool['pool_id']),
            'DeleteMap': SUCCEED,
            'CreateReplica': FAKE_ERROR_RETURN,
            'CreateMap': SUCCEED,
            'ShowLV': self._mock_show_lv_for_migrate
        }
        self._driver_setup(mock_commands)

        ex = self.assertRaises(
            exception.InfortrendCliException,
            self.driver.migrate_volume,
            test_volume,
            test_host)

        self.assertTrue(re.match(
            r'.*Failed to create replica.*', ex.msg))

    def test_manage_existing_get_size(self):

        test_volume = self.cli_data.test_volume
        test_ref_volume = self.cli_data.test_ref_volume
        test_pool = self.cli_data.fake_lv_id[0]
        test_partition_id = self.cli_data.fake_partition_id[2]

        mock_commands = {
            'ShowPartition': self.cli_data.get_test_show_partition_detail(
                test_ref_volume['source-id'].replace('-', ''), test_pool),
            'ShowMap': SUCCEED
        }

        self._driver_setup(mock_commands)

        size = self.driver.manage_existing_get_size(
            test_volume, test_ref_volume)

        expect_cli_cmd = [
            mock.call('ShowMap', 'part=%s' % test_partition_id)
        ]
        self._assert_cli_has_calls(expect_cli_cmd)
        self.assertEqual(size, 0)

    def test_manage_existing_get_size_in_use(self):

        test_volume = self.cli_data.test_volume
        test_ref_volume = self.cli_data.test_ref_volume
        test_pool = self.cli_data.fake_lv_id[0]

        mock_commands = {
            'ShowPartition': self.cli_data.get_test_show_partition_detail(
                test_ref_volume['source-id'].replace('-', ''), test_pool),
            'ShowMap': self.cli_data.get_test_show_map()
        }
        self._driver_setup(mock_commands)

        ex = self.assertRaises(
            exception.InfortrendAPIException,
            self.driver.manage_existing_get_size,
            test_volume,
            test_ref_volume)

        self.assertTrue(re.match(
            r'.*The specified volume is mapped to a host.*', ex.msg))

    def test_manage_existing_get_size_no_source_id(self):

        test_volume = self.cli_data.test_volume
        test_ref_volume = self.cli_data.test_dst_volume
        self.driver = self._get_driver(self.configuration)

        ex = self.assertRaises(
            exception.InfortrendAPIException,
            self.driver.manage_existing_get_size,
            test_volume,
            test_ref_volume)

        self.assertTrue(re.match(
            r'.*Reference must contain source-id element.*', ex.msg))

    def test_manage_existing_get_size_show_part_fail(self):

        test_volume = self.cli_data.test_volume
        test_ref_volume = self.cli_data.test_ref_volume

        mock_commands = {
            'ShowPartition': FAKE_ERROR_RETURN,
            'ShowMap': SUCCEED
        }
        self._driver_setup(mock_commands)

        ex = self.assertRaises(
            exception.InfortrendCliException,
            self.driver.manage_existing_get_size,
            test_volume,
            test_ref_volume)

        self.assertTrue(re.match(
            r'.*Failed to get partition info.*', ex.msg))

    def test_manage_existing_get_size_show_map_fail(self):

        test_volume = self.cli_data.test_volume
        test_ref_volume = self.cli_data.test_ref_volume

        mock_commands = {
            'ShowPartition': self.cli_data.get_test_show_partition_detail(),
            'ShowMap': FAKE_ERROR_RETURN
        }
        self._driver_setup(mock_commands)

        ex = self.assertRaises(
            exception.InfortrendCliException,
            self.driver.manage_existing_get_size,
            test_volume,
            test_ref_volume)

        self.assertTrue(re.match(
            r'.*Failed to get map info.*', ex.msg))

    @mock.patch.object(LOG, 'info')
    def test_manage_existing(self, log_info):

        test_volume = self.cli_data.test_volume
        test_ref_volume = self.cli_data.test_ref_volume
        test_pool = self.cli_data.fake_lv_id[0]
        test_partition_id = self.cli_data.fake_partition_id[2]

        mock_commands = {
            'ShowPartition': self.cli_data.get_test_show_partition_detail(
                test_ref_volume['source-id'].replace('-', ''), test_pool),
            'SetPartition': SUCCEED
        }
        self._driver_setup(mock_commands)

        self.driver.manage_existing(
            test_volume, test_ref_volume)

        expect_cli_cmd = [
            mock.call('SetPartition', test_partition_id,
                      'name=%s' % test_volume['id'].replace('-', ''))
        ]
        self._assert_cli_has_calls(expect_cli_cmd)
        log_info.assert_called_once_with(
            'Rename Volume %s done', test_volume['id'])

    def test_manage_existing_rename_fail(self):

        test_volume = self.cli_data.test_volume
        test_ref_volume = self.cli_data.test_ref_volume
        test_pool = self.cli_data.fake_lv_id[0]

        mock_commands = {
            'ShowPartition': self.cli_data.get_test_show_partition_detail(
                test_ref_volume['source-id'].replace('-', ''), test_pool),
            'SetPartition': FAKE_ERROR_RETURN
        }

        self._driver_setup(mock_commands)

        ex = self.assertRaises(
            exception.InfortrendCliException,
            self.driver.manage_existing,
            test_volume,
            test_ref_volume)

        self.assertTrue(re.match(
            r'.*Failed to set partition.*', ex.msg))
