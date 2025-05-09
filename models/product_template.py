from odoo import api, fields, models
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # Champ pour stocker la référence au produit miroir dans l'autre société
    sync_product_id = fields.Many2one(
        'product.template',
        string='Produit miroir',
        help="Référence au produit correspondant dans l'autre société",
        copy=False
    )

    is_synced = fields.Boolean(
        string='Est synchronisé',
        compute='_compute_is_synced',
        store=True,
        help="Indique si ce produit a été synchronisé avec l'autre société"
    )

    @api.depends('sync_product_id')
    def _compute_is_synced(self):
        for product in self:
            product.is_synced = bool(product.sync_product_id)

    @api.model_create_multi
    def create(self, vals_list):
        """Surcharge pour synchroniser après création"""
        products = super(ProductTemplate, self).create(vals_list)

        # Ne synchronise que si configuré pour le faire
        mappings = self.env['dz.company.mapping'].search([
            ('source_company_id', '=', self.env.company.id),
            ('sync_products', '=', True),
            ('auto_sync', '=', True),
        ])

        if mappings:
            # Préférer la synchronisation en arrière-plan pour les gros volumes
            if len(products) > 3:
                # Tenter la synchronisation en file d'attente
                if mappings[0]._sync_in_background('product.template', products.ids, 'create'):
                    return products
            # Sinon, synchronisation directe
            for product in products:
                try:
                    product._sync_to_target_company(mappings[0])
                except Exception as e:
                    _logger.error("Erreur lors de la synchronisation du produit %s: %s", product.name, str(e), exc_info=True)

        return products

    def write(self, vals):
        """Surcharge pour synchroniser après modification"""
        result = super(ProductTemplate, self).write(vals)

        # Ne déclenche la synchronisation que si des champs importants ont été modifiés
        important_fields = ['name', 'default_code', 'list_price', 'standard_price',
                            'taxes_id', 'supplier_taxes_id', 'type', 'categ_id', 'uom_id']

        if any(field in vals for field in important_fields):
            for product in self:
                if product.sync_product_id:
                    try:
                        product._update_mirror_product(vals)
                    except Exception as e:
                        _logger.error("Erreur lors de la mise à jour du produit miroir %s: %s",
                                      product.name, str(e))

        return result

    def _sync_to_target_company(self, mapping):
        """Synchronise ce produit vers la société cible"""
        self.ensure_one()

        if self.sync_product_id:
            return  # Déjà synchronisé

        if not mapping or not mapping.sync_products:
            return  # Pas de mapping ou synchronisation désactivée

        target_company = mapping.target_company_id

        # Vérifier si un produit avec la même référence existe déjà dans la cible
        if self.default_code:
            existing_product = self.with_company(target_company).search([
                ('default_code', '=', self.default_code),
                ('company_id', '=', target_company.id)
            ], limit=1)

            if existing_product:
                # Lier les produits existants
                self.sync_product_id = existing_product.id
                existing_product.sync_product_id = self.id
                return existing_product

        # Préparer les valeurs pour la création du produit miroir
        product_vals = {
            'name': self.name,
            'default_code': self.default_code,
            'type': self.type,
            'categ_id': self.categ_id.id,  # Supposant que les catégories sont partagées
            'list_price': self.list_price,
            'standard_price': self.standard_price,
            'uom_id': self.uom_id.id,  # Supposant que les UoM sont partagées
            'uom_po_id': self.uom_po_id.id,
            'purchase_ok': self.purchase_ok,
            'sale_ok': self.sale_ok,
            'active': self.active,
            'company_id': target_company.id,
        }

        # Gestion des taxes (nécessite un mappage des taxes entre les sociétés)
        # Cette partie est simplifiée et pourrait nécessiter un mappage plus complexe
        # selon la configuration fiscale de chaque société

        # Changer de société temporairement
        current_company = self.env.company
        self.env.company = target_company

        try:
            # Créer le produit miroir
            mirror_product = self.with_company(target_company).create(product_vals)

            # Désactiver la synchronisation récursive
            mirror_product._origin.write({'sync_product_id': self.id})
            self.sync_product_id = mirror_product.id

            _logger.info("Produit %s synchronisé vers la société %s (ID: %s)",
                         self.name, target_company.name, mirror_product.id)

            return mirror_product

        finally:
            # Restaurer la société d'origine
            self.env.company = current_company

    def _update_mirror_product(self, vals):
        """Met à jour le produit miroir avec les nouvelles valeurs"""
        self.ensure_one()

        if not self.sync_product_id:
            return  # Pas de produit miroir

        mirror_product = self.sync_product_id
        target_company = mirror_product.company_id

        # Préparer les valeurs pour la mise à jour
        update_vals = {}
        field_mapping = {
            'name': 'name',
            'default_code': 'default_code',
            'type': 'type',
            'categ_id': 'categ_id',
            'list_price': 'list_price',
            'standard_price': 'standard_price',
            'uom_id': 'uom_id',
            'uom_po_id': 'uom_po_id',
            'purchase_ok': 'purchase_ok',
            'sale_ok': 'sale_ok',
            'active': 'active',
        }

        for source_field, target_field in field_mapping.items():
            if source_field in vals:
                update_vals[target_field] = vals[source_field]

        if update_vals:
            # Changer de société temporairement
            current_company = self.env.company
            self.env.company = target_company

            try:
                # Mettre à jour le produit miroir
                mirror_product.with_context(skip_sync=True).write(update_vals)

                _logger.info("Produit miroir %s mis à jour dans la société %s",
                             mirror_product.name, target_company.name)

            finally:
                # Restaurer la société d'origine
                self.env.company = current_company

    def action_sync_product(self):
        """Action pour synchroniser manuellement un produit"""
        self.ensure_one()

        mappings = self.env['dz.company.mapping'].search([
            ('source_company_id', '=', self.env.company.id),
            ('sync_products', '=', True),
        ], limit=1)

        if not mappings:
            raise UserError(_("Aucun mappage trouvé pour synchroniser les produits."))

        if self.sync_product_id:
            self._update_mirror_product({
                'name': self.name,
                'default_code': self.default_code,
                'type': self.type,
                'categ_id': self.categ_id.id,
                'list_price': self.list_price,
                'standard_price': self.standard_price,
                'uom_id': self.uom_id.id,
                'uom_po_id': self.uom_po_id.id,
                'purchase_ok': self.purchase_ok,
                'sale_ok': self.sale_ok,
                'active': self.active,
            })
            message = _("Le produit a été mis à jour dans la société cible.")
        else:
            self._sync_to_target_company(mappings[0])
            message = _("Le produit a été synchronisé vers la société cible.")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Synchronisation réussie'),
                'message': message,
                'type': 'success',
                'sticky': False,
            }
        }
