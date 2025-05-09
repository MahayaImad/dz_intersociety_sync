from odoo import api, models
import logging

_logger = logging.getLogger(__name__)

class SyncQueue(models.AbstractModel):
    _name = 'dz.sync.queue'
    _description = 'Gestionnaire de file d\'attente pour les synchronisations'

    @api.model
    def _sync_to_target_company_job(self, record_ids, mapping_id):
        """Méthode exécutée par la file d'attente pour synchroniser des enregistrements"""
        mapping = self.env['dz.company.mapping'].browse(mapping_id)
        if not mapping.exists():
            return False

        model_name = self.env.context.get('active_model')
        if not model_name:
            return False

        records = self.env[model_name].browse(record_ids)
        success_count = 0
        error_count = 0

        for record in records:
            try:
                record._sync_to_target_company(mapping)
                success_count += 1
            except Exception as e:
                error_count += 1
                _logger.error("Échec de la synchronisation en file d'attente pour %s (ID: %s): %s",
                             model_name, record.id, str(e), exc_info=True)

        _logger.info("Synchronisation en file d'attente terminée pour %s enregistrements %s: %s réussis, %s échoués",
                   len(records), model_name, success_count, error_count)
        return True
