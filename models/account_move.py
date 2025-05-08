from odoo import api, fields, models
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    # Champ pour stocker la référence à la facture miroir dans l'autre société
    sync_move_id = fields.Many2one(
        'account.move',
        string='Facture miroir',
        help="Référence à la facture correspondante dans l'autre société",
        copy=False
    )

    is_synced = fields.Boolean(
        string='Est synchronisé',
        compute='_compute_is_synced',
        store=True,
        help="Indique si ce document a été synchronisé avec l'autre société"
    )

    @api.depends('sync_move_id')
    def _compute_is_synced(self):
        for move in self:
            move.is_synced = bool(move.sync_move_id)

    def _get_valid_mappings(self):
        """Récupère les mappages valides pour cette société"""
        return self.env['dz.company.mapping'].search([
            '|',
            ('source_company_id', '=', self.company_id.id),
            ('target_company_id', '=', self.company_id.id),
            ('sync_invoices', '=', True),
            ('auto_sync', '=', True),
        ])

    def action_post(self):
        """Surcharge pour synchroniser après validation"""
        result = super(AccountMove, self).action_post()

        # Si nous sommes dans une facture et pas déjà synchronisée
        for move in self.filtered(lambda m: m.move_type in ('out_invoice', 'in_invoice') and not m.sync_move_id):
            mappings = move._get_valid_mappings()

            # Si nous sommes dans la société source et que nous avons un mapping
            if mappings and any(mapping.source_company_id == move.company_id for mapping in mappings):
                try:
                    move._sync_to_target_company()
                except Exception as e:
                    _logger.error("Erreur lors de la synchronisation de la facture %s: %s", move.name, str(e))

        return result

    def _sync_to_target_company(self):
        """Synchronise cette facture vers la société cible"""
        self.ensure_one()

        if self.sync_move_id:
            return  # Déjà synchronisé

        # Recherche le mapping approprié
        mapping = self.env['dz.company.mapping'].search([
            ('source_company_id', '=', self.company_id.id),
            ('sync_invoices', '=', True),
        ], limit=1)

        if not mapping:
            return  # Pas de mapping trouvé

        target_company = mapping.target_company_id

        # Changer de société temporairement
        current_company = self.env.company
        self.env.company = target_company

        try:
            #TODO: Ici nous créerons la facture miroir dans la société cible
            # Ce code sera développé dans la prochaine étape

            # Exemple simplifié:
            mirror_move = self.with_company(target_company).copy({
                'company_id': target_company.id,
                # Les autres champs seraient adaptés ici
            })

            # Lier les deux factures
            self.sync_move_id = mirror_move.id
            mirror_move.sync_move_id = self.id

            _logger.info("Facture %s synchronisée vers la société %s (ID: %s)",
                         self.name, target_company.name, mirror_move.id)

        finally:
            # Restaurer la société d'origine
            self.env.company = current_company
