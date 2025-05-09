from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    # Champ pour stocker la référence à la commande miroir dans l'autre société
    sync_purchase_id = fields.Many2one(
        'purchase.order',
        string='Commande miroir',
        help="Référence à la commande d'achat correspondante dans l'autre société",
        copy=False
    )

    is_synced = fields.Boolean(
        string='Est synchronisé',
        compute='_compute_is_synced',
        store=True,
        help="Indique si cette commande a été synchronisée avec l'autre société"
    )

    @api.depends('sync_purchase_id')
    def _compute_is_synced(self):
        for order in self:
            order.is_synced = bool(order.sync_purchase_id)

    def _sync_to_target_company(self, mapping):
        """Synchronise cette commande d'achat vers la société cible"""
        self.ensure_one()

        if self.sync_purchase_id:
            _logger.info("La commande %s est déjà synchronisée. ID miroir: %s", self.name, self.sync_purchase_id.id)
            return  # Déjà synchronisé

        if not mapping or not mapping.sync_purchases:
            _logger.warning("Synchronisation impossible pour la commande %s: mapping invalide ou désactivé", self.name)
            return  # Pas de mapping ou synchronisation désactivée

        # Ajout d'identifiants pour le traçage
        sync_trace_id = f"{self._name}_{self.id}_{fields.Datetime.now().strftime('%Y%m%d%H%M%S')}"
        _logger.info("[%s] Début de la synchronisation de la commande %s vers la société %s",
                     sync_trace_id, self.name, mapping.target_company_id.name)

        target_company = mapping.target_company_id

        # Synchroniser d'abord le fournisseur si nécessaire
        partner = self.partner_id
        if not partner.sync_partner_id and mapping.sync_partners:
            partner._sync_to_target_company(mapping)

        if not partner.sync_partner_id:
            raise UserError(_("Le fournisseur %s doit être synchronisé avant la commande.") % partner.name)

        target_partner = partner.sync_partner_id

        # Changer de société temporairement
        current_company = self.env.company
        self.env.company = target_company

        try:
            # Créer l'entête de la commande
            purchase_vals = {
                'partner_id': target_partner.id,
                'currency_id': self.currency_id.id,
                'date_order': self.date_order,
                'date_planned': self.date_planned,
                'partner_ref': self.partner_ref,
                'origin': self.origin,
                'notes': self.notes,
                'payment_term_id': self.payment_term_id.id,
                'company_id': target_company.id,
                'fiscal_position_id': self._get_target_fiscal_position(target_company).id,
            }

            mirror_order = self.env['purchase.order'].with_company(target_company).create(purchase_vals)

            # Ajouter les lignes de commande
            for line in self.order_line:
                # Synchroniser le produit si nécessaire
                product = line.product_id
                if product and not product.sync_product_id and mapping.sync_products:
                    product._sync_to_target_company(mapping)

                target_product = product.sync_product_id if product and product.sync_product_id else False

                if not target_product:
                    continue  # Ignorer les lignes sans produit synchronisé

                # Créer la ligne
                line_vals = {
                    'order_id': mirror_order.id,
                    'name': line.name,
                    'product_id': target_product.id,
                    'product_qty': line.product_qty,
                    'product_uom': line.product_uom.id,
                    'price_unit': line.price_unit,
                    'taxes_id': [(6, 0, self._get_target_taxes(line.taxes_id, target_company).ids)],
                    'date_planned': line.date_planned,
                }

                self.env['purchase.order.line'].with_company(target_company).create(line_vals)

            # Lier les deux commandes
            self.sync_purchase_id = mirror_order.id
            mirror_order.sync_purchase_id = self.id

            _logger.info("Commande d'achat %s synchronisée vers la société %s (ID: %s)",
                         self.name, target_company.name, mirror_order.id)

            return mirror_order

        finally:
            # Restaurer la société d'origine
            self.env.company = current_company

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

    def button_confirm(self):
        """Surcharge pour synchroniser après confirmation"""
        result = super(PurchaseOrder, self).button_confirm()

        # Vérifier si nous devons synchroniser cette commande
        if self.state in ['purchase', 'done']:
            mappings = self.env['dz.company.mapping'].search([
                ('source_company_id', '=', self.company_id.id),
                ('sync_purchases', '=', True),
                ('auto_sync', '=', True),
            ])

            # Si nous sommes dans la société source et que nous avons un mapping
            if mappings and not self.sync_purchase_id:
                try:
                    self._sync_to_target_company(mappings[0])
                except Exception as e:
                    _logger.error("Erreur lors de la synchronisation de la commande %s: %s", self.name, str(e))

        return result

    def action_create_invoice(self):
        """Surcharge pour synchroniser la facture créée"""
        result = super(PurchaseOrder, self).action_create_invoice()

        # Si une facture a été créée et que nous devons la synchroniser
        if result and isinstance(result, dict) and result.get('res_id'):
            invoice_id = result.get('res_id')
            invoice = self.env['account.move'].browse(invoice_id)

            if invoice.exists():
                # Vérifier si nous devons synchroniser cette facture
                mappings = self.env['dz.company.mapping'].search([
                    ('source_company_id', '=', self.company_id.id),
                    ('sync_invoices', '=', True),
                    ('auto_sync', '=', True),
                ])

                if mappings and not invoice.sync_move_id:
                    try:
                        invoice._sync_to_target_company()
                    except Exception as e:
                        _logger.error("Erreur lors de la synchronisation de la facture %s: %s",
                                      invoice.name, str(e))

        return result

    def action_sync_purchase(self):
        """Action pour synchroniser manuellement une commande d'achat"""
        self.ensure_one()

        mappings = self.env['dz.company.mapping'].search([
            ('source_company_id', '=', self.env.company.id),
            ('sync_purchases', '=', True),
        ], limit=1)

        if not mappings:
            raise UserError(_("Aucun mappage trouvé pour synchroniser les commandes d'achat."))

        mirror_order = self._sync_to_target_company(mappings[0])

        if mirror_order:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Synchronisation réussie'),
                    'message': _("La commande d'achat a été synchronisée vers la société cible."),
                    'type': 'success',
                    'sticky': False,
                    'next': {
                        'type': 'ir.actions.act_window',
                        'res_model': 'purchase.order',
                        'res_id': mirror_order.id,
                        'views': [(False, 'form')],
                    }
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Échec de synchronisation'),
                    'message': _("La synchronisation de la commande d'achat a échoué."),
                    'type': 'danger',
                    'sticky': True,
                }
            }
