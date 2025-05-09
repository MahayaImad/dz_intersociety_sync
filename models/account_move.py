from odoo import api, fields, models, _
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

    def action_sync_invoice(self):
        """Action pour synchroniser manuellement une facture"""
        self.ensure_one()

        mappings = self.env['dz.company.mapping'].search([
            ('source_company_id', '=', self.env.company.id),
            ('sync_invoices', '=', True),
        ], limit=1)

        if not mappings:
            raise UserError(_("Aucun mappage trouvé pour synchroniser les factures."))

        result = self._sync_to_target_company()

        if result:
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

    def _sync_to_target_company(self):
        """Synchronise cette facture vers la société cible"""
        self.ensure_one()

        # Si déjà synchronisée, rien à faire
        if self.sync_move_id:
            return self.sync_move_id

        # Recherche le mapping approprié
        mapping = self.env['dz.company.mapping'].search([
            ('source_company_id', '=', self.company_id.id),
            ('sync_invoices', '=', True),
        ], limit=1)

        if not mapping:
            _logger.warning("Pas de mappage trouvé pour synchroniser la facture %s", self.name)
            return False

        target_company = mapping.target_company_id

        # Synchroniser d'abord le partenaire si nécessaire
        partner = self.partner_id
        if partner and not partner.sync_partner_id and mapping.sync_partners:
            try:
                # Vérifier si le modèle a la méthode
                if hasattr(partner, '_sync_to_target_company'):
                    partner._sync_to_target_company(mapping)
                else:
                    _logger.warning("La méthode _sync_to_target_company n'existe pas sur res.partner")
            except Exception as e:
                _logger.error("Erreur lors de la synchronisation du partenaire %s: %s", partner.name, str(e))

        # Obtenir le partenaire cible
        target_partner = partner.sync_partner_id if partner and hasattr(partner, 'sync_partner_id') else partner

        # Changer de société temporairement
        current_company = self.env.company
        self.env.company = target_company

        try:
            # Créer l'entête de la facture
            move_vals = {
                'move_type': self.move_type,
                'partner_id': target_partner.id if target_partner else False,
                'currency_id': self.currency_id.id,
                'invoice_date': self.invoice_date,
                'date': self.date,
                'invoice_date_due': self.invoice_date_due,
                'ref': self.ref,
                'narration': self.narration,
                'payment_reference': self.payment_reference,
                'invoice_payment_term_id': self.invoice_payment_term_id.id if self.invoice_payment_term_id else False,
                'company_id': target_company.id,
                'invoice_origin': self.invoice_origin or self.name,
            }

            # Créer la facture miroir
            mirror_move = self.with_company(target_company).create(move_vals)

            # Ajouter les lignes de facture
            for line in self.invoice_line_ids:
                # Synchroniser le produit si nécessaire
                product = line.product_id
                if product and mapping.sync_products and hasattr(product,
                                                                 'sync_product_id') and not product.sync_product_id:
                    try:
                        if hasattr(product, '_sync_to_target_company'):
                            product._sync_to_target_company(mapping)
                    except Exception as e:
                        _logger.error("Erreur lors de la synchronisation du produit %s: %s", product.name, str(e))

                # Obtenir le produit cible
                target_product = product.sync_product_id if product and hasattr(product, 'sync_product_id') else product

                # Créer la ligne de facture
                line_vals = {
                    'move_id': mirror_move.id,
                    'name': line.name,
                    'product_id': target_product.id if target_product else False,
                    'quantity': line.quantity,
                    'price_unit': line.price_unit,
                    'discount': line.discount,
                    'tax_ids': [(6, 0, self._get_target_taxes(line.tax_ids, target_company).ids)],
                    'account_id': self._get_target_account(line.account_id,
                                                           target_company).id if self._get_target_account(
                        line.account_id, target_company) else False,
                }

                self.env['account.move.line'].with_company(target_company).create(line_vals)

            # Lier les deux factures
            self.sync_move_id = mirror_move.id
            mirror_move.sync_move_id = self.id

            # Si la facture d'origine est validée, valider également la facture miroir
            if self.state == 'posted':
                mirror_move.action_post()

            _logger.info("Facture %s synchronisée vers la société %s (ID: %s)",
                         self.name, target_company.name, mirror_move.id)

            return mirror_move

        except Exception as e:
            _logger.error("Erreur lors de la synchronisation de la facture %s: %s", self.name, str(e))
            return False
        finally:
            # Restaurer la société d'origine
            self.env.company = current_company

    def _get_target_account(self, source_account, target_company):
        """Obtient le compte correspondant dans la société cible"""
        if not source_account:
            return self.env['account.account']

        # Chercher par code et type
        target_account = self.env['account.account'].search([
            ('code', '=', source_account.code),
            ('company_id', '=', target_company.id)
        ], limit=1)

        if not target_account:
            # Si pas trouvé par code, chercher par nom
            target_account = self.env['account.account'].search([
                ('name', '=', source_account.name),
                ('company_id', '=', target_company.id)
            ], limit=1)

        return target_account

    def _get_target_taxes(self, source_taxes, target_company):
        """Obtient les taxes correspondantes dans la société cible"""
        target_taxes = self.env['account.tax']

        for tax in source_taxes:
            # Chercher une taxe avec le même code et type
            target_tax = self.env['account.tax'].search([
                ('name', '=', tax.name),
                ('type_tax_use', '=', tax.type_tax_use),
                ('company_id', '=', target_company.id)
            ], limit=1)

            if target_tax:
                target_taxes += target_tax

        return target_taxes

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
                    _logger.error("Erreur lors de la synchronisation de la facture %s: %s", move.name, str(e),
                                  exc_info=True)
                    # Notifier l'utilisateur de l'échec
                    self.env.user.notify_warning(
                        title="Échec de synchronisation",
                        message=f"La facture {move.name} n'a pas pu être synchronisée. Vérifiez les journaux pour plus de détails."
                    )

        return result

    def _get_target_fiscal_position(self, target_company):
        """Obtient la position fiscale correspondante dans la société cible"""
        if not self.fiscal_position_id:
            return self.env['account.fiscal.position']

        # Chercher par nom
        target_fiscal_position = self.env['account.fiscal.position'].search([
            ('name', '=', self.fiscal_position_id.name),
            ('company_id', '=', target_company.id)
        ], limit=1)

        return target_fiscal_position
