 #from cinder import interface
from cinder.openstack.common import log as logging
from cinder.volume import driver
from cinder.volume.drivers.infortrend.raidcmd_cli import common_cli

LOG = logging.getLogger(__name__)
LOG.debug('123456789')
class FC_VolumeDriver(driver.VolumeDriver):
    #CI_WIKI_NAME = "Infortrend_Storage_CI"
    VERSION = common_cli.InfortrendCommon.VERSION  #2.1.3
    def __init__(self, *args, **kwargs):
        super(FC_VolumeDriver, self).__init__(*args, **kwargs)
        self.common = common_cli.InfortrendCommon(
            'FC', configuration=self.configuration)
        self.VERSION = self.common.VERSION
    def do_setup(self,context):
        '''
        if self.ip == '':
            msg = _('san_ip is not set.')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)
        '''
        LOG.debug('do_setup start')
        self.common.do_setup()
    def check_for_setup_error(self):
        LOG.debug('check_for_setup_error start')
        self.common.check_for_setup_error()
    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, run update the stats first.
        """
        LOG.debug('get_volume_stats refresh=%(refresh)s', {
            'refresh': refresh})
        return self.common.get_volume_stats(refresh)
    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection information.

        Assign any created volume to a compute node/host so that it can be
        used from that host.

        The  driver returns a driver_volume_type of 'fibre_channel'.
        The target_wwn can be a single entry or a list of wwns that
        correspond to the list of remote wwn(s) that will export the volume.
        The initiator_target_map is a map that represents the remote wwn(s)
        and a list of wwns which are visible to the remote wwn(s).
        Example return values:
        """
        LOG.debug(
            'initialize_connection volume id=%(volume_id)s '
            'connector initiator=%(initiator)s', {
                'volume_id': volume['id'],
                'initiator': connector['initiator']})
        return self.common.initialize_connection(volume, connector)
    def create_volume(self, volume):
        """Create a Infortrend partition."""
        LOG.debug('volume is')
        LOG.debug(volume)
        LOG.debug('create_volume volume id=%(volume_id)s', {
            'volume_id': volume['id']})
        return self.common.create_volume(volume)
    def delete_volume(self, volume):
        """Deletes a volume."""
        LOG.debug('delete_volume volume id=%(volume_id)s', {
            'volume_id': volume['id']})
        return self.common.delete_volume(volume)
    def remove_export(self, context, volume):
        """Removes an export for a volume."""
        LOG.info('start delete_volume')
    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        LOG.debug('terminate_connection volume id=%(volume_id)s', {
            'volume_id': volume['id']})
        self.common.terminate_connection(volume, connector)
    def extend_volume(self, volume, new_size):
        """Extend a volume."""
        LOG.debug(
            'extend_volume volume id=%(volume_id)s new size=%(size)s', {
                'volume_id': volume['id'], 'size': new_size})
        self.common.extend_volume(volume, new_size)
    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        LOG.debug(
            'create_volume_from_snapshot volume id=%(volume_id)s '
            'snapshot id=%(snapshot_id)s', {
                'volume_id': volume['id'], 'snapshot_id': snapshot['id']})
        return self.common.create_volume_from_snapshot(volume, snapshot)
    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        LOG.debug(
            'create_snapshot snapshot id=%(snapshot_id)s '
            'volume_id=%(volume_id)s', {
                'snapshot_id': snapshot['id'],
                'volume_id': snapshot['volume_id']})
        return self.common.create_snapshot(snapshot)
    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        LOG.debug(
            'delete_snapshot snapshot id=%(snapshot_id)s '
            'volume_id=%(volume_id)s', {
                'snapshot_id': snapshot['id'],
                'volume_id': snapshot['volume_id']})
        self.common.delete_snapshot(snapshot)
    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        LOG.debug(
            'create_cloned_volume volume id=%(volume_id)s '
            'src_vref provider_location=%(provider_location)s', {
                'volume_id': volume['id'],
                'provider_location': src_vref['provider_location']})
        return self.common.create_cloned_volume(volume, src_vref)
   #def migrate_volume(self, ctxt, volume, host):
    def migrate_volume(self, ctxt, volume, host):
        """Migrate the volume to the specified host.

        Returns a boolean indicating whether the migration occurred, as well as
        model_update.

        :param ctxt: Context
        :param volume: A dictionary describing the volume to migrate
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        """
        LOG.debug('migrate_volume volume id=%(volume_id)s host=%(host)s', {
            'volume_id': volume['id'], 'host': host['host']})
        return self.common.migrate_volume(volume, host)

    def retype(self, ctxt, volume, new_type, diff, host):
        """Convert the volume to be of the new type.

        :param ctxt: Context
        :param volume: A dictionary describing the volume to migrate
        :param new_type: A dictionary describing the volume type to convert to
        :param diff: A dictionary with the difference between the two types
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        """
        LOG.debug(
            'retype volume id=%(volume_id)s new_type id=%(type_id)s', {
                'volume_id': volume['id'], 'type_id': new_type['id']})
        return self.common.retype(ctxt, volume, new_type, diff, host)
    def manage_existing(self, volume, existing_ref):
        """Manage an existing lun in the array.

        The lun should be in a manageable pool backend, otherwise
        error would return.
        Rename the backend storage object so that it matches the,
        volume['name'] which is how drivers traditionally map between a
        cinder volume and the associated backend storage object.

        :param existing_ref: Driver-specific information used to identify
                             a volume
        """
        LOG.debug(
            'manage_existing volume: %(volume)s '
            'existing_ref source: %(source)s', {
                'volume': volume,
                'source': existing_ref})
        return self.common.manage_existing(volume, existing_ref)
    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of volume to be managed by manage_existing.

        When calculating the size, round up to the next GB.
        """
        LOG.debug(
            'manage_existing_get_size volume: %(volume)s '
            'existing_ref source: %(source)s', {
                'volume': volume,
                'source': existing_ref})
        return self.common.manage_existing_get_size(volume, existing_ref)
    def unmanage(self, volume):
        """Removes the specified volume from Cinder management.

        Does not delete the underlying backend storage object.

        :param volume: Cinder volume to unmanage
        """
        LOG.debug('unmanage volume id=%(volume_id)s', {
            'volume_id': volume['id']})
        self.common.unmanage(volume)
    def create_export(self, context, volume, ):
        """Exports the volume.

        Can optionally return a Dictionary of changes
        to the volume object to be persisted.
        """
        LOG.debug(
            'create_export volume provider_location=%(provider_location)s', {
                'provider_location': volume['provider_location']})
        return self.common.create_export(context, volume)
    def copy_image_to_volume(self, context, volume, image_service, image_id):
        LOG.debug('111122223333')
        LOG.debug('copyimage context is')
        LOG.debug(context.__dict__)
        LOG.debug('copyimage voluem is')
        LOG.debug(volume.__dict__)
        LOG.debug('copyimage voluem[_sa_instance_state] is')
        LOG.debug(volume['_sa_instance_state'].__dict__)
 
        LOG.debug('image_service is')
        LOG.debug(image_service.__dict__)
        LOG.debug('image_service[_client] is')
       # LOG.debug(image_service['_client'].__dict__)
 
        LOG.debug('image_id is')
        LOG.debug(image_id)
        LOG.debug('444455556666')

