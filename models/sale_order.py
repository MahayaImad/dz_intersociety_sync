from odoo import api, fields, models
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # Champ pour stocker la référence à la commande miroir dans l'autre société
    sync_order_id = fields.Many2one(
        'sale.order',
        string='Commande miroir',
        help="Référence à la commande correspondante dans l'autre société",
        copy=False
    )

    is_synced = fields.Boolean(
        string='Est synchronisé',
        compute='_compute_is_synced',
        store=True,
        help="Indique si cette commande a été synchronisée avec l'autre société"
    )

    sync_date = fields.Datetime(string="Date de synchronisation", readonly=True)
    sync_user_id = fields.Many2one('res.users', string="Synchronisé par", readonly=True)

    # Champs calculés pour accéder aux informations de la commande miroir
    mirror_order_state = fields.Selection(
        string="État de la commande miroir",
        selection=[
            ('draft', 'Devis'),
            ('sent', 'Devis envoyé'),
            ('sale', 'Bon de commande'),
            ('done', 'Verrouillé'),
            ('cancel', 'Annulé'),
        ],
        compute='_compute_mirror_order_info'
    )

    mirror_order_amount = fields.Monetary(
        string="Montant total de la commande miroir",
        compute='_compute_mirror_order_info',
        currency_field='currency_id'
    )

    @api.depends('sync_order_id', 'sync_order_id.state', 'sync_order_id.amount_total')
    def _compute_mirror_order_info(self):
        for order in self:
            if order.sync_order_id:
                order.mirror_order_state = order.sync_order_id.state
                order.mirror_order_amount = order.sync_order_id.amount_total
            else:
                order.mirror_order_state = False
                order.mirror_order_amount = 0.0

    @api.depends('sync_order_id')
    def _compute_is_synced(self):
        for order in self:
            order.is_synced = bool(order.sync_order_id)

    def action_sync_sale_order(self):
        """Action pour synchroniser manuellement une commande de vente"""
        self.ensure_one()

        mappings = self.env['dz.company.mapping'].search([
            ('source_company_id', '=', self.env.company.id),
            ('sync_sales', '=', True),
        ], limit=1)

        if not mappings:
            raise UserError(_("Aucun mappage trouvé pour synchroniser les commandes de vente."))

        mirror_order = self._sync_to_target_company(mappings[0])

        if mirror_order:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Synchronisation réussie'),
                    'message': _("La commande de vente a été synchronisée vers la société cible."),
                    'type': 'success',
                    'sticky': False,
                    'next': {
                        'type': 'ir.actions.act_window',
                        'res_model': 'sale.order',
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
                    'message': _("La synchronisation de la commande de vente a échoué."),
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def _sync_to_target_company(self, mapping):
        """Synchronise cette commande de vente vers la société cible"""
        self.ensure_one()

        if self.sync_order_id:
            return self.sync_order_id  # Déjà synchronisé

        if not mapping or not mapping.sync_sales:
            return False  # Pas de mapping ou synchronisation désactivée

        target_company = mapping.target_company_id

        # Synchroniser d'abord le client si nécessaire
        partner = self.partner_id
        if not partner.sync_partner_id and mapping.sync_partners:
            partner._sync_to_target_company(mapping)

        if not partner.sync_partner_id:
            raise UserError(_("Le client %s doit être synchronisé avant la commande.") % partner.name)

        target_partner = partner.sync_partner_id

        # Changer de société temporairement
        current_company = self.env.company
        self.env.company = target_company

        try:
            # Créer l'entête de la commande
            order_vals = {
                'partner_id': target_partner.id,
                'partner_invoice_id': self.partner_invoice_id.sync_partner_id.id if self.partner_invoice_id.sync_partner_id else target_partner.id,
                'partner_shipping_id': self.partner_shipping_id.sync_partner_id.id if self.partner_shipping_id.sync_partner_id else target_partner.id,
                'date_order': self.date_order,
                'validity_date': self.validity_date,
                'pricelist_id': self.pricelist_id.id,  # Les listes de prix sont généralement partagées
                'payment_term_id': self.payment_term_id.id,
                'company_id': target_company.id,
                'user_id': self.user_id.id,  # Les utilisateurs sont partagés entre sociétés
                'team_id': self.team_id.id,
                'client_order_ref': self.client_order_ref,
                'origin': self.name,
            }

            mirror_order = self.env['sale.order'].with_company(target_company).create(order_vals)

            # Ajouter les lignes de commande
            for line in self.order_line:
                # Synchroniser le produit si nécessaire
                product = line.product_id
                if product and not product.sync_product_id and mapping.sync_products:
                    product._sync_to_target_company(mapping)

                target_product = product.sync_product_id if product and product.sync_product_id else product

                if not target_product:
                    continue  # Ignorer les lignes sans produit synchronisé

                # Créer la ligne
                line_vals = {
                    'order_id': mirror_order.id,
                    'name': line.name,
                    'product_id': target_product.id,
                    'product_uom_qty': line.product_uom_qty,
                    'product_uom': line.product_uom.id,
                    'price_unit': line.price_unit,
                    'discount': line.discount,
                    'tax_id': [(6, 0, self._get_target_taxes(line.tax_id, target_company).ids)],
                }

                self.env['sale.order.line'].with_company(target_company).create(line_vals)

            # Lier les deux commandes
            self.write({
                'sync_order_id': mirror_order.id,
                'sync_date': fields.Datetime.now(),
                'sync_user_id': self.env.user.id,
            })
            mirror_order.sync_order_id = self.id

            # Si la commande d'origine est confirmée, confirmer également la commande miroir
            if self.state == 'sale':
                mirror_order.action_confirm()

            _logger.info("Commande de vente %s synchronisée vers la société %s (ID: %s)",
                         self.name, target_company.name, mirror_order.id)

            return mirror_order

        except Exception as e:
            _logger.error("Erreur lors de la synchronisation de la commande de vente %s: %s", self.name, str(e))
            return False
        finally:
            # Restaurer la société d'origine
            self.env.company = current_company

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

    def _create_invoices(self, grouped=False, final=False, date=None):
        """Surcharge pour détecter la création de facture à partir d'une commande"""
        # Appel de la méthode standard
        moves = super(SaleOrder, self)._create_invoices(grouped=grouped, final=final, date=date)

        # Vérifier si nous devons synchroniser les factures créées
        for move in moves:
            self.env['stock.picking']._check_and_sync_invoice(move)

        return moves
    @api.model
    def _sync_to_target_company_safe(self, mapping):
        """Version sécurisée de la synchronisation avec gestion des transactions"""
        self.ensure_one()

        # Création d'un savepoint
        savepoint_name = f"sync_sale_{self.id}_{fields.Datetime.now().strftime('%Y%m%d%H%M%S')}"
        self.env.cr.savepoint(savepoint_name)

        try:
            result = self._sync_to_target_company(mapping)
            return result
        except Exception as e:
            # En cas d'erreur, annuler les modifications
            self.env.cr.savepoint_rollback(savepoint_name)
            _logger.error("Erreur lors de la synchronisation de la commande %s: %s", self.name, str(e), exc_info=True)
            raise
