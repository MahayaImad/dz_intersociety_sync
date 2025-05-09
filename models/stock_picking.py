from odoo import api, fields, models
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    is_invoiced = fields.Boolean(
        string='Est facturé',
        compute='_compute_is_invoiced',
        store=True,
        help="Indique si ce bon de livraison a été facturé"
    )

    # Calcul sans dépendance sur stock.move.sale_line_ids qui n'existe pas
    def _compute_is_invoiced(self):
        """Vérifie si le bon de livraison est facturé en recherchant les factures liées"""
        for picking in self:
            picking.is_invoiced = False

            # Si ce n'est pas un BL client, on considère comme non facturé
            if picking.picking_type_code != 'outgoing':
                continue

            # Pour les livraisons liées à des commandes de vente
            if picking.sale_id:
                # Vérifier si une des factures liées à la commande est validée
                if any(invoice.state == 'posted' for invoice in picking.sale_id.invoice_ids):
                    picking.is_invoiced = True
                continue

            # Pour les livraisons qui n'ont pas de lien direct avec une commande
            # Essayer de trouver les factures via le nom d'origine
            if picking.origin:
                invoices = self.env['account.move'].search([
                    ('invoice_origin', '=', picking.origin),
                    ('move_type', '=', 'out_invoice'),
                    ('state', '=', 'posted')
                ])
                if invoices:
                    picking.is_invoiced = True

    @api.model
    def _check_and_sync_invoice(self, invoice):
        """Vérifier si une facture vient d'un BL et la synchroniser si nécessaire"""
        # Ne considérer que les factures émises validées
        if invoice.state != 'posted' or invoice.move_type not in ('out_invoice', 'out_refund'):
            return

        # Rechercher les bons de livraison potentiellement liés à cette facture
        pickings = False

        # 1. Via la commande de vente si disponible
        if invoice.invoice_origin:
            sale_orders = self.env['sale.order'].search([('name', '=', invoice.invoice_origin)])
            if sale_orders:
                pickings = self.search([('sale_id', 'in', sale_orders.ids)])

        # 2. Via l'origine de la facture si pas de livraison trouvée
        if not pickings and invoice.invoice_origin:
            pickings = self.search([('origin', '=', invoice.invoice_origin)])

        if not pickings:
            return

        # Vérifie si la facture doit être synchronisée
        mappings = self.env['dz.company.mapping'].search([
            ('source_company_id', '=', invoice.company_id.id),
            ('sync_invoices', '=', True),
            ('auto_sync', '=', True),
        ])

        if mappings and not invoice.sync_move_id:
            try:
                _logger.info(
                    f"Synchronisation automatique de la facture {invoice.name} issue des BL {', '.join(pickings.mapped('name'))}")
                invoice._sync_to_target_company()
            except Exception as e:
                _logger.error("Erreur lors de la synchronisation automatique de la facture %s: %s",
                              invoice.name, str(e))
