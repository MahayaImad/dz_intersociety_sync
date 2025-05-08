from odoo import api, fields, models
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # Champ pour stocker la référence au partenaire miroir dans l'autre société
    sync_partner_id = fields.Many2one(
        'res.partner',
        string='Partenaire miroir',
        help="Référence au partenaire correspondant dans l'autre société",
        copy=False
    )

    is_synced = fields.Boolean(
        string='Est synchronisé',
        compute='_compute_is_synced',
        store=True,
        help="Indique si ce partenaire a été synchronisé avec l'autre société"
    )

    @api.depends('sync_partner_id')
    def _compute_is_synced(self):
        for partner in self:
            partner.is_synced = bool(partner.sync_partner_id)

    @api.model_create_multi
    def create(self, vals_list):
        """Surcharge pour synchroniser après création"""
        partners = super(ResPartner, self).create(vals_list)

        # Ne synchronise que les partenaires principaux (pas les adresses de livraison/facturation)
        for partner in partners.filtered(lambda p: not p.parent_id):
            mappings = self.env['dz.company.mapping'].search([
                ('source_company_id', '=', self.env.company.id),
                ('sync_partners', '=', True),
                ('auto_sync', '=', True),
            ])

            if mappings:
                try:
                    partner._sync_to_target_company(mappings[0])
                except Exception as e:
                    _logger.error("Erreur lors de la synchronisation du partenaire %s: %s", partner.name, str(e))

        return partners

    def write(self, vals):
        """Surcharge pour synchroniser après modification"""
        result = super(ResPartner, self).write(vals)

        # Ne déclenche la synchronisation que si des champs importants ont été modifiés
        important_fields = ['name', 'street', 'street2', 'zip', 'city', 'country_id',
                            'email', 'phone', 'mobile', 'vat', 'company_type']

        if any(field in vals for field in important_fields):
            for partner in self.filtered(lambda p: not p.parent_id):
                if partner.sync_partner_id:
                    try:
                        partner._update_mirror_partner(vals)
                    except Exception as e:
                        _logger.error("Erreur lors de la mise à jour du partenaire miroir %s: %s",
                                      partner.name, str(e))

        return result

    def _sync_to_target_company(self, mapping):
        """Synchronise ce partenaire vers la société cible"""
        self.ensure_one()

        if self.sync_partner_id:
            return  # Déjà synchronisé

        if not mapping or not mapping.sync_partners:
            return  # Pas de mapping ou synchronisation désactivée

        target_company = mapping.target_company_id

        # Vérifier si un partenaire avec le même numéro de TVA existe déjà dans la cible
        if self.vat:
            existing_partner = self.with_company(target_company).search([
                ('vat', '=', self.vat),
                ('company_id', '=', target_company.id)
            ], limit=1)

            if existing_partner:
                # Lier les partenaires existants
                self.sync_partner_id = existing_partner.id
                existing_partner.sync_partner_id = self.id
                return existing_partner

        # Préparer les valeurs pour la création du partenaire miroir
        partner_vals = {
            'name': self.name,
            'company_type': self.company_type,
            'street': self.street,
            'street2': self.street2,
            'zip': self.zip,
            'city': self.city,
            'state_id': self.state_id.id,
            'country_id': self.country_id.id,
            'email': self.email,
            'phone': self.phone,
            'mobile': self.mobile,
            'vat': self.vat,
            'company_id': target_company.id,
        }

        # Changer de société temporairement
        current_company = self.env.company
        self.env.company = target_company

        try:
            # Créer le partenaire miroir
            mirror_partner = self.with_company(target_company).create(partner_vals)

            # Désactiver la synchronisation récursive
            mirror_partner._origin.write({'sync_partner_id': self.id})
            self.sync_partner_id = mirror_partner.id

            _logger.info("Partenaire %s synchronisé vers la société %s (ID: %s)",
                         self.name, target_company.name, mirror_partner.id)

            # Synchroniser les adresses de contact associées
            for child in self.child_ids:
                child_vals = {
                    'name': child.name,
                    'type': child.type,
                    'street': child.street,
                    'street2': child.street2,
                    'zip': child.zip,
                    'city': child.city,
                    'state_id': child.state_id.id,
                    'country_id': child.country_id.id,
                    'email': child.email,
                    'phone': child.phone,
                    'mobile': child.mobile,
                    'parent_id': mirror_partner.id,
                    'company_id': target_company.id,
                }

                child_mirror = self.with_company(target_company).create(child_vals)
                child.sync_partner_id = child_mirror.id
                child_mirror.write({'sync_partner_id': child.id})

            return mirror_partner

        finally:
            # Restaurer la société d'origine
            self.env.company = current_company

    def _update_mirror_partner(self, vals):
        """Met à jour le partenaire miroir avec les nouvelles valeurs"""
        self.ensure_one()

        if not self.sync_partner_id:
            return  # Pas de partenaire miroir

        mirror_partner = self.sync_partner_id
        target_company = mirror_partner.company_id

        # Préparer les valeurs pour la mise à jour
        update_vals = {}
        field_mapping = {
            'name': 'name',
            'company_type': 'company_type',
            'street': 'street',
            'street2': 'street2',
            'zip': 'zip',
            'city': 'city',
            'state_id': 'state_id',
            'country_id': 'country_id',
            'email': 'email',
            'phone': 'phone',
            'mobile': 'mobile',
            'vat': 'vat',
        }

        for source_field, target_field in field_mapping.items():
            if source_field in vals:
                update_vals[target_field] = vals[source_field]

        if update_vals:
            # Changer de société temporairement
            current_company = self.env.company
            self.env.company = target_company

            try:
                # Mettre à jour le partenaire miroir
                mirror_partner.with_context(skip_sync=True).write(update_vals)

                _logger.info("Partenaire miroir %s mis à jour dans la société %s",
                             mirror_partner.name, target_company.name)

            finally:
                # Restaurer la société d'origine
                self.env.company = current_company

    def action_sync_partner(self):
        """Action pour synchroniser manuellement un partenaire"""
