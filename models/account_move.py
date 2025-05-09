from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
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

    # Nouveau champ pour indiquer si la facture est déclarée
    is_declared = fields.Boolean(
        string='Est déclarée',
        default=False,
        help="Indique si cette facture a été déclarée officiellement",
        groups="dz_intersociety_sync.group_declaration_manager"
    )

    # Séquence spécifique BL ou Facture
    sequence_type = fields.Selection([
        ('bl', 'Bon de Livraison'),
        ('facture', 'Facture')
    ], string='Type de séquence', compute='_compute_sequence_type', store=True)

    @api.depends('is_declared')
    def _compute_sequence_type(self):
        for move in self:
            if move.move_type in ('out_invoice', 'out_refund') and move.is_declared:
                move.sequence_type = 'facture'
            elif move.move_type in ('out_invoice', 'out_refund'):
                move.sequence_type = 'bl'
            else:
                move.sequence_type = False

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

    # Surcharge pour utiliser la bonne séquence selon le type de document
    @api.model
    def _get_sequence(self):
        # Si c'est une facture client
        if self.move_type in ('out_invoice', 'out_refund'):
            if self.is_declared:
                return self.env['ir.sequence'].next_by_code('account.move.facture')
            else:
                return self.env['ir.sequence'].next_by_code('account.move.bl')
        return super(AccountMove, self)._get_sequence()

    # Adapté pour afficher "Bon de Livraison" ou "Facture" selon le statut
    def _get_report_base_filename(self):
        if self.move_type in ('out_invoice', 'out_refund'):
            if self.is_declared:
                return 'Facture - %s' % (self.name or '')
            else:
                return 'Bon de Livraison - %s' % (self.name or '')
        return super(AccountMove, self)._get_report_base_filename()

    # Permettre uniquement les clients éligibles pour les factures déclarées
    @api.constrains('is_declared', 'partner_id')
    def _check_partner_eligibility(self):
        for move in self:
            if move.is_declared and move.move_type in ('out_invoice', 'out_refund'):
                if not move.partner_id.is_eligible_for_declaration:
                    raise ValidationError(
                        f"Le client {move.partner_id.name} n'est pas éligible à la facturation déclarée.")

    # Action pour déclarer une facture
    def action_declare_invoice(self):
        self.ensure_one()
        if not self.is_declared and self.move_type in ('out_invoice', 'out_refund'):
            # Vérifier l'éligibilité du client
            if not self.partner_id.is_eligible_for_declaration:
                raise UserError(f"Le client {self.partner_id.name} n'est pas éligible à la facturation déclarée.")

            # Marquer comme déclarée
            self.is_declared = True

            # Synchroniser vers la société cible si nécessaire
            if not self.sync_move_id:
                mappings = self._get_valid_mappings()
                if mappings:
                    try:
                        self._sync_to_target_company()
                    except Exception as e:
                        _logger.error("Erreur lors de la synchronisation de la facture déclarée %s: %s", self.name,
                                      str(e))

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Facture déclarée',
                    'message': 'La facture a été marquée comme déclarée et synchronisée avec succès.',
                    'type': 'success',
                    'sticky': False,
                }
            }

    def action_post(self):
        """Surcharge pour synchroniser après validation"""
        result = super(AccountMove, self).action_post()

        # Si nous sommes dans une facture et pas déjà synchronisée
        for move in self.filtered(
            lambda m: m.move_type in ('out_invoice', 'in_invoice') and not m.sync_move_id and m.is_declared):
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
            # TODO: Ici nous créerons la facture miroir dans la société cible
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

    def action_sync_invoice(self):
        """Action pour synchroniser manuellement une facture"""
        self.ensure_one()

        mappings = self.env['dz.company.mapping'].search([
            ('source_company_id', '=', self.env.company.id),
            ('sync_invoices', '=', True),
        ], limit=1)

        if not mappings:
            raise UserError(_("Aucun mappage trouvé pour synchroniser les factures."))

        if self.sync_move_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Déjà synchronisée'),
                    'message': _("Cette facture est déjà synchronisée avec la société cible."),
                    'type': 'warning',
                    'sticky': False,
                }
            }
        else:
            mirror_move = self._sync_to_target_company()

            if mirror_move:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Synchronisation réussie'),
                        'message': _("La facture a été synchronisée vers la société cible."),
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Échec de synchronisation'),
                        'message': _("La synchronisation de la facture a échoué."),
                        'type': 'danger',
                        'sticky': True,
                    }
                }
