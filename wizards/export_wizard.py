from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class ExportWizard(models.TransientModel):
    _name = 'dz.export.wizard'
    _description = 'Assistant d\'exportation vers société officielle'

    # Ajouter le champ company_id
    company_id = fields.Many2one(
        'res.company',
        string='Société',
        default=lambda self: self.env.company,
        required=True
    )

    # Configuration
    mapping_id = fields.Many2one(
        'dz.company.mapping',
        string='Mappage',
        required=True,
        help="Sélectionnez le mappage entre sociétés à utiliser"
    )

    export_partners = fields.Boolean(string='Exporter les clients', default=True)
    export_products = fields.Boolean(string='Exporter les produits', default=True)
    export_invoices = fields.Boolean(string='Exporter les factures', default=True)

    date_from = fields.Date(string='Date de début')
    date_to = fields.Date(string='Date de fin', default=fields.Date.today)

    # États de l'assistant
    state = fields.Selection([
        ('config', 'Configuration'),
        ('verification', 'Vérification'),
        ('done', 'Terminé')
    ], default='config')

    # Résultats des vérifications
    verification_result = fields.Text(string='Résultat des vérifications', readonly=True)

    # Statistiques
    partners_count = fields.Integer('Clients à exporter', compute='_compute_counts')
    products_count = fields.Integer('Produits à exporter', compute='_compute_counts')
    invoices_count = fields.Integer('Factures à exporter', compute='_compute_counts')

    @api.depends('export_partners', 'export_products', 'export_invoices', 'date_from', 'date_to')
    def _compute_counts(self):
        for wizard in self:
            # Comptage des partenaires à exporter
            partner_domain = [('company_id', '=', self.env.company.id), ('is_synced', '=', False)]
            if wizard.date_from:
                partner_domain.append(('create_date', '>=', wizard.date_from))
            if wizard.date_to:
                partner_domain.append(('create_date', '<=', wizard.date_to))
            wizard.partners_count = self.env['res.partner'].search_count(partner_domain) if wizard.export_partners else 0

            # Comptage des produits à exporter
            product_domain = [('company_id', '=', self.env.company.id), ('is_synced', '=', False)]
            if wizard.date_from:
                product_domain.append(('create_date', '>=', wizard.date_from))
            if wizard.date_to:
                product_domain.append(('create_date', '<=', wizard.date_to))
            wizard.products_count = self.env['product.template'].search_count(product_domain) if wizard.export_products else 0

            # Comptage des factures à exporter
            invoice_domain = [
                ('move_type', 'in', ('out_invoice', 'out_refund')),
                ('company_id', '=', self.env.company.id),
                ('is_synced', '=', False),
                ('state', '=', 'posted'),
                ('is_declared', '=', True)
            ]
            if wizard.date_from:
                invoice_domain.append(('invoice_date', '>=', wizard.date_from))
            if wizard.date_to:
                invoice_domain.append(('invoice_date', '<=', wizard.date_to))
            wizard.invoices_count = self.env['account.move'].search_count(invoice_domain) if wizard.export_invoices else 0

    @api.onchange('mapping_id')
    def _onchange_mapping_id(self):
        if self.mapping_id:
            self.export_partners = self.mapping_id.sync_partners
            self.export_products = self.mapping_id.sync_products
            self.export_invoices = self.mapping_id.sync_invoices

    def action_verify(self):
        """Vérifier les données avant l'exportation"""
        self.ensure_one()

        warnings = []

        # 1. Vérifier les partenaires non éligibles
        if self.export_invoices:
            warnings.extend(self._check_partner_eligibility())

        # 2. Vérifier les produits vendus mais non achetés
        if self.export_products or self.export_invoices:
            warnings.extend(self._check_products_not_purchased())

        # 3. Vérifier les quantités en stock
        if self.export_products or self.export_invoices:
            warnings.extend(self._check_stock_availability())

        # Préparation du résultat
        if warnings:
            self.verification_result = _("⚠️ Problèmes détectés:\n\n") + "\n".join(warnings)
        else:
            self.verification_result = _("✅ Aucun problème détecté. Vous pouvez procéder à l'exportation.")

        self.state = 'verification'
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'dz.export.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _check_partner_eligibility(self):
        """Vérifier l'éligibilité des clients pour les factures à exporter"""
        warnings = []

        invoice_domain = [
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('company_id', '=', self.env.company.id),
            ('is_synced', '=', False),
            ('state', '=', 'posted'),
            ('is_declared', '=', True)
        ]
        if self.date_from:
            invoice_domain.append(('invoice_date', '>=', self.date_from))
        if self.date_to:
            invoice_domain.append(('invoice_date', '<=', self.date_to))

        invoices = self.env['account.move'].search(invoice_domain)

        for invoice in invoices:
            if not invoice.partner_id.is_eligible_for_declaration:
                warnings.append(_("• La facture %s est pour le client %s qui n'est pas éligible à la facturation déclarée.")
                               % (invoice.name, invoice.partner_id.name))

        return warnings

    def _check_products_not_purchased(self):
        """Vérifier les produits vendus mais non achetés"""
        warnings = []

        invoice_domain = [
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('company_id', '=', self.env.company.id),
            ('state', '=', 'posted')
        ]
        if self.date_from:
            invoice_domain.append(('invoice_date', '>=', self.date_from))
        if self.date_to:
            invoice_domain.append(('invoice_date', '<=', self.date_to))

        invoices = self.env['account.move'].search(invoice_domain)

        for invoice in invoices:
            for line in invoice.invoice_line_ids:
                if line.product_id and line.product_id.type == 'product':
                    # Vérifier si le produit a été acheté
                    purchase_count = self.env['account.move.line'].search_count([
                        ('move_id.move_type', '=', 'in_invoice'),
                        ('move_id.state', '=', 'posted'),
                        ('product_id', '=', line.product_id.id)
                    ])

                    if purchase_count == 0:
                        warnings.append(_("• Le produit %s (facture %s) est vendu sans achat préalable.")
                                       % (line.product_id.name, invoice.name))

        return warnings

    def _check_stock_availability(self):
        """Vérifier la disponibilité des stocks"""
        warnings = []

        if not self.mapping_id:
            return warnings

        target_company = self.mapping_id.target_company_id

        # Obtenir tous les produits stockables vendus
        invoice_domain = [
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('company_id', '=', self.env.company.id),
            ('state', '=', 'posted')
        ]
        if self.date_from:
            invoice_domain.append(('invoice_date', '>=', self.date_from))
        if self.date_to:
            invoice_domain.append(('invoice_date', '<=', self.date_to))

        invoices = self.env['account.move'].search(invoice_domain)

        for invoice in invoices:
            for line in invoice.invoice_line_ids:
                if line.product_id and line.product_id.type == 'product':
                    # Vérifier la disponibilité dans la société cible
                    if line.product_id.sync_product_id:
                        target_product = line.product_id.sync_product_id

                        # Vérifier le stock disponible
                        stock_quant = self.env['stock.quant'].with_company(target_company).search([
                            ('product_id', '=', target_product.product_variant_id.id),
                            ('location_id.usage', '=', 'internal')
                        ])

                        available_qty = sum(q.quantity for q in stock_quant)

                        if available_qty < line.quantity:
                            warnings.append(_("• Stock insuffisant pour le produit %s dans la société cible (disponible: %s, requis: %s)")
                                           % (line.product_id.name, available_qty, line.quantity))

        return warnings

    def action_export(self):
        """Exécuter l'exportation des données"""
        self.ensure_one()

        if not self.mapping_id:
            raise UserError(_("Vous devez sélectionner un mappage pour continuer."))

        # Statistiques d'exportation
        stats = {
            'partners': {'success': 0, 'failed': 0},
            'products': {'success': 0, 'failed': 0},
            'invoices': {'success': 0, 'failed': 0}
        }

        # 1. Exporter les partenaires
        if self.export_partners:
            partner_domain = [
                ('company_id', '=', self.env.company.id),
                ('is_synced', '=', False),
                ('parent_id', '=', False)  # Uniquement les partenaires principaux
            ]
            if self.date_from:
                partner_domain.append(('create_date', '>=', self.date_from))
            if self.date_to:
                partner_domain.append(('create_date', '<=', self.date_to))

            partners = self.env['res.partner'].search(partner_domain)

            for partner in partners:
                try:
                    partner._sync_to_target_company(self.mapping_id)
                    stats['partners']['success'] += 1
                except Exception as e:
                    stats['partners']['failed'] += 1
                    _logger.error("Erreur lors de l'exportation du partenaire %s: %s", partner.name, str(e))

        # 2. Exporter les produits
        if self.export_products:
            product_domain = [
                ('company_id', '=', self.env.company.id),
                ('is_synced', '=', False)
            ]
            if self.date_from:
                product_domain.append(('create_date', '>=', self.date_from))
            if self.date_to:
                product_domain.append(('create_date', '<=', self.date_to))

            products = self.env['product.template'].search(product_domain)

            for product in products:
                try:
                    product._sync_to_target_company(self.mapping_id)
                    stats['products']['success'] += 1
                except Exception as e:
                    stats['products']['failed'] += 1
                    _logger.error("Erreur lors de l'exportation du produit %s: %s", product.name, str(e))

        # 3. Exporter les factures
        if self.export_invoices:
            invoice_domain = [
                ('move_type', 'in', ('out_invoice', 'out_refund')),
                ('company_id', '=', self.env.company.id),
                ('is_synced', '=', False),
                ('state', '=', 'posted'),
                ('is_declared', '=', True)
            ]
            if self.date_from:
                invoice_domain.append(('invoice_date', '>=', self.date_from))
            if self.date_to:
                invoice_domain.append(('invoice_date', '<=', self.date_to))

            invoices = self.env['account.move'].search(invoice_domain)

            for invoice in invoices:
                try:
                    invoice._sync_to_target_company()
                    stats['invoices']['success'] += 1
                except Exception as e:
                    stats['invoices']['failed'] += 1
                    _logger.error("Erreur lors de l'exportation de la facture %s: %s", invoice.name, str(e))

        # Mettre à jour la date de dernière synchronisation du mapping
        self.mapping_id.write({'last_sync_date': fields.Datetime.now()})

        # Préparer le résumé
        summary = _("Résumé de l'exportation:\n\n")
        summary += _("• Clients: %d exportés avec succès, %d échoués\n") % (
        stats['partners']['success'], stats['partners']['failed'])
        summary += _("• Produits: %d exportés avec succès, %d échoués\n") % (
        stats['products']['success'], stats['products']['failed'])
        summary += _("• Factures: %d exportées avec succès, %d échouées\n") % (
        stats['invoices']['success'], stats['invoices']['failed'])

        self.verification_result = summary
        self.state = 'done'

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'dz.export.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
