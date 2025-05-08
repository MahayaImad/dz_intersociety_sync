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

    @api.depends('sync_order_id')
    def _compute_is_synced(self):
        for order in self:
            order.is_synced = bool(order.sync_order_id)

    def _create_invoices(self, grouped=False, final=False, date=None):
        """Surcharge pour détecter la création de facture à partir d'une commande"""
        # Appel de la méthode standard
        moves = super(SaleOrder, self)._create_invoices(grouped=grouped, final=final, date=date)

        # Vérifier si nous devons synchroniser les factures créées
        for move in moves:
            self.env['stock.picking']._check_and_sync_invoice(move)

        return moves
