from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class SyncWizard(models.TransientModel):
    _name = 'dz.sync.wizard'
    _description = 'Assistant de synchronisation inter-sociétés'

    mapping_id = fields.Many2one(
        'dz.company.mapping',
        string='Mappage',
        required=True,
        help="Sélectionnez le mappage entre sociétés à utiliser"
    )

    sync_partners = fields.Boolean(string='Synchroniser les partenaires', default=True)
    sync_products = fields.Boolean(string='Synchroniser les produits', default=True)
    sync_invoices = fields.Boolean(string='Synchroniser les factures', default=True)
    sync_sales = fields.Boolean(string='Synchroniser les ventes', default=True)
    sync_purchases = fields.Boolean(string='Synchroniser les achats', default=True)

    date_from = fields.Date(string='Date de début')
    date_to = fields.Date(string='Date de fin', default=fields.Date.today)

    summary = fields.Text(string='Résumé des opérations', readonly=True)

    @api.onchange('mapping_id')
    def _onchange_mapping_id(self):
        if self.mapping_id:
            self.sync_partners = self.mapping_id.sync_partners
            self.sync_products = self.mapping_id.sync_products
            self.sync_invoices = self.mapping_id.sync_invoices
            self.sync_sales = self.mapping_id.sync_sales
            self.sync_purchases = self.mapping_id.sync_purchases

    def action_sync(self):
        self.ensure_one()

        if not self.mapping_id:
            raise UserError(_("Vous devez sélectionner un mappage pour continuer."))

        source_company = self.mapping_id.source_company_id
        target_company = self.mapping_id.target_company_id

        # Résultats des opérations
        results = {
            'partners': {'synced': 0, 'updated': 0, 'failed': 0},
            'products': {'synced': 0, 'updated': 0, 'failed': 0},
            'invoices': {'synced': 0, 'failed': 0},
            'sales': {'synced': 0, 'failed': 0},
            'purchases': {'synced': 0, 'failed': 0},
        }

        # 1. Synchroniser les partenaires
        if self.sync_partners:
            domain = [('company_id', '=', source_company.id)]
            if self.date_from:
                domain.append(('create_date', '>=', self.date_from))
            if self.date_to:
                domain.append(('create_date', '<=', self.date_to))

            partners = self.env['res.partner'].search(domain)

            for partner in partners:
                try:
                    if partner.sync_partner_id:
                        partner._update_mirror_partner({
                            'name': partner.name,
                            'company_type': partner.company_type,
                            'street': partner.street,
                            'street2': partner.street2,
                            'zip': partner.zip,
                            'city': partner.city,
                            'state_id': partner.state_id.id,
                            'country_id': partner.country_id.id,
                            'email': partner.email,
                            'phone': partner.phone,
                            'mobile': partner.mobile,
                            'vat': partner.vat,
                        })
                        results['partners']['updated'] += 1
                    else:
                        partner._sync_to_target_company(self.mapping_id)
                        results['partners']['synced'] += 1
                except Exception as e:
                    _logger.error("Erreur lors de la synchronisation du partenaire %s: %s", partner.name, str(e))
                    results['partners']['failed'] += 1

        # 2. Synchroniser les produits
        if self.sync_products:
            domain = [('company_id', '=', source_company.id)]
            if self.date_from:
                domain.append(('create_date', '>=', self.date_from))
            if self.date_to:
                domain.append(('create_date', '<=', self.date_to))

            products = self.env['product.template'].search(domain)

            for product in products:
                try:
                    if product.sync_product_id:
                        product._update_mirror_product({
                            'name': product.name,
                            'default_code': product.default_code,
                            'type': product.type,
                            'categ_id': product.categ_id.id,
                            'list_price': product.list_price,
                            'standard_price': product.standard_price,
                            'uom_id': product.uom_id.id,
                            'uom_po_id': product.uom_po_id.id,
                            'purchase_ok': product.purchase_ok,
                            'sale_ok': product.sale_ok,
                            'active': product.active,
                        })
                        results['products']['updated'] += 1
                    else:
                        product._sync_to_target_company(self.mapping_id)
                        results['products']['synced'] += 1
                except Exception as e:
                    _logger.error("Erreur lors de la synchronisation du produit %s: %s", product.name, str(e))
                    results['products']['failed'] += 1

        # 3. Synchroniser les factures
        if self.sync_invoices:
            domain = [
                ('company_id', '=', source_company.id),
                ('move_type', 'in', ['out_invoice', 'in_invoice']),
                ('state', '=', 'posted'),
                ('is_synced', '=', False)
            ]
            if self.date_from:
                domain.append(('invoice_date', '>=', self.date_from))
            if self.date_to:
                domain.append(('invoice_date', '<=', self.date_to))

            invoices = self.env['account.move'].search(domain)

            for invoice in invoices:
                try:
                    invoice._sync_to_target_company()
                    results['invoices']['synced'] += 1
                except Exception as e:
                    _logger.error("Erreur lors de la synchronisation de la facture %s: %s", invoice.name, str(e))
                    results['invoices']['failed'] += 1
        # 4. Synchroniser les achats
        if self.sync_purchases:
            domain = [
                ('company_id', '=', source_company.id),
                ('state', 'in', ['purchase', 'done']),
                ('is_synced', '=', False)
            ]
            if self.date_from:
                domain.append(('date_order', '>=', self.date_from))
            if self.date_to:
                domain.append(('date_order', '<=', self.date_to))

            purchase_orders = self.env['purchase.order'].search(domain)

            for order in purchase_orders:
                try:
                    order._sync_to_target_company(self.mapping_id)
                    results['purchases']['synced'] += 1
                except Exception as e:
                    _logger.error("Erreur lors de la synchronisation de la commande d'achat %s: %s", order.name, str(e))
                    results['purchases']['failed'] += 1

        # Mettre à jour la date de dernière synchronisation
        self.mapping_id.write({'last_sync_date': fields.Datetime.now()})

        # Préparer le résumé des opérations
        summary = _("Résumé de la synchronisation :\n\n")
        summary += _("Partenaires : %d synchronisés, %d mis à jour, %d échoués\n") % (
            results['partners']['synced'], results['partners']['updated'], results['partners']['failed'])
        summary += _("Produits : %d synchronisés, %d mis à jour, %d échoués\n") % (
            results['products']['synced'], results['products']['updated'], results['products']['failed'])
        summary += _("Factures : %d synchronisées, %d échouées\n") % (
            results['invoices']['synced'], results['invoices']['failed'])

        if self.sync_sales:
            summary += _("Ventes : non implémenté dans cette version\n")

        if self.sync_purchases:
            summary += _("Achats : non implémenté dans cette version\n")

        # Mettre à jour le résumé et afficher le formulaire mis à jour
        self.write({'summary': summary})

        return {
            'name': _('Résultat de la synchronisation'),
            'type': 'ir.actions.act_window',
            'res_model': 'dz.sync.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
