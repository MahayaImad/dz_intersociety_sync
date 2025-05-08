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

    @api.depends('move_ids.invoice_line_ids')
    def _compute_is_invoiced(self):
        for picking in self:
            picking.is_invoiced = any(
                move.invoice_line_ids.filtered(lambda l: l.move_id.state == 'posted') for move in picking.move_ids)

    @api.model
    def _check_and_sync_invoice(self, invoice):
        """Vérifier si une facture vient d'un BL et la synchroniser si nécessaire"""
        # Recherche les BL associés à cette facture
        pickings = self.env['stock.picking'].search([
            ('move_ids.invoice_line_ids.move_id', '=', invoice.id)
        ])

        if pickings and invoice.state == 'posted':
            # Vérifie si la facture doit être synchronisée
            mappings = self.env['dz.company.mapping'].search([
                ('source_company_id', '=', invoice.company_id.id),
                ('sync_invoices', '=', True),
                ('auto_sync', '=', True),
            ])

            if mappings and not invoice.sync_move_id:
                try:
                    _logger.info("Synchronisation automatique de la facture %s issue du BL", invoice.name)
                    invoice._sync_to_target_company()
                except Exception as e:
                    _logger.error("Erreur lors de la synchronisation automatique de la facture %s: %s",
                                  invoice.name, str(e))
