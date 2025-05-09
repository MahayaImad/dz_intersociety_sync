# -*- coding: utf-8 -*-
from odoo import api, fields, models
import logging

_logger = logging.getLogger(__name__)

class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    # On réimplémente cette méthode qui est problématique
    # La version simplifiée évite les problèmes d'accès
    def _get_invoice_lines(self):
        """Méthode sécurisée pour obtenir les lignes de facture associées"""
        try:
            return super(PurchaseOrderLine, self)._get_invoice_lines()
        except Exception as e:
            _logger.warning("Erreur lors de l'accès aux lignes de facture pour la ligne d'achat %s: %s",
                          self.name, str(e))
            return self.env['account.move.line']
