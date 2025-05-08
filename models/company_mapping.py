from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class CompanyMapping(models.Model):
    _name = 'dz.company.mapping'
    _description = 'Mappage entre sociétés pour le contexte algérien'

    name = fields.Char(string='Nom', required=True)
    active = fields.Boolean(default=True)

    source_company_id = fields.Many2one(
        'res.company',
        string='Société source (complète)',
        required=True,
        help="Société contenant toutes les opérations (facturées et non facturées)"
    )

    target_company_id = fields.Many2one(
        'res.company',
        string='Société cible (officielle)',
        required=True,
        help="Société contenant uniquement les opérations facturées officiellement"
    )

    auto_sync = fields.Boolean(
        string='Synchronisation automatique',
        default=True,
        help="Si activé, les documents éligibles seront automatiquement synchronisés"
    )

    sync_partners = fields.Boolean(string='Synchroniser les partenaires', default=True)
    sync_products = fields.Boolean(string='Synchroniser les produits', default=True)
    sync_invoices = fields.Boolean(string='Synchroniser les factures', default=True)
    sync_sales = fields.Boolean(string='Synchroniser les ventes', default=True)
    sync_purchases = fields.Boolean(string='Synchroniser les achats', default=True)

    last_sync_date = fields.Datetime(string='Dernière synchronisation', readonly=True)

    _sql_constraints = [
        ('unique_mapping', 'unique(source_company_id, target_company_id)',
         'Un mappage entre ces deux sociétés existe déjà!')
    ]

    @api.constrains('source_company_id', 'target_company_id')
    def _check_different_companies(self):
        for record in self:
            if record.source_company_id == record.target_company_id:
                raise ValidationError(_("Les sociétés source et cible doivent être différentes."))

    def action_sync_now(self):
        """Déclenche manuellement la synchronisation"""
        self.ensure_one()

        #TODO: à implémenter aprés la logique

        self.write({'last_sync_date': fields.Datetime.now()})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Synchronisation effectuée'),
                'message': _('La synchronisation entre %s et %s a été effectuée avec succès.') %
                           (self.source_company_id.name, self.target_company_id.name),
                'type': 'success',
                'sticky': False,
            }
        }
