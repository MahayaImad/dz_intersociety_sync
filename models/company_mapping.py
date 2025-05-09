from odoo import api, fields, models,_
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

        # Création d'un savepoint pour pouvoir annuler en cas d'erreur
        savepoint_name = f"sync_now_{self.id}_{fields.Datetime.now().strftime('%Y%m%d%H%M%S')}"
        self.env.cr.savepoint(savepoint_name)

        try:
            # Créer un assistant de synchronisation et l'exécuter
            wizard = self.env['dz.sync.wizard'].create({
                'mapping_id': self.id,
                'sync_partners': self.sync_partners,
                'sync_products': self.sync_products,
                'sync_invoices': self.sync_invoices,
                'sync_sales': self.sync_sales,
                'sync_purchases': self.sync_purchases,
            })

            # Exécuter le wizard et récupérer le résumé
            result = wizard.action_sync()
            summary = wizard.summary or ""

            # Mettre à jour la date de dernière synchronisation
            self.write({'last_sync_date': fields.Datetime.now()})

            # Retourner une notification de succès avec le résumé
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Synchronisation effectuée'),
                    'message': _('La synchronisation entre %s et %s a été effectuée avec succès.\n\n%s') %
                               (self.source_company_id.name, self.target_company_id.name, summary),
                    'type': 'success',
                    'sticky': True,  # Mettre à True pour que l'utilisateur puisse lire le résumé
                }
            }
        except Exception as e:
            # Restaurer l'état précédent en cas d'erreur
            self.env.cr.savepoint_rollback(savepoint_name)
            _logger.error("Erreur lors de la synchronisation manuelle: %s", str(e), exc_info=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Échec de synchronisation'),
                    'message': str(e),
                    'type': 'danger',
                    'sticky': True,
                }
            }
    def _sync_in_background(self, model_name, record_ids, sync_type='create'):
        """Ajoute des tâches de synchronisation à la file d'attente"""
        # Vérifiez si le module queue_job est installé
        if not self.env['ir.module.module'].search([('name', '=', 'queue_job'), ('state', '=', 'installed')]):
            return False

        # Importation dynamique pour éviter des erreurs si le module n'est pas installé
        self.env['queue.job'].create({
            'name': f"Synchronisation {sync_type} - {model_name} ({len(record_ids)} enregistrements)",
            'model_name': model_name,
            'method_name': '_sync_to_target_company_job',
            'args': [record_ids, self.id],
            'channel': 'dz_intersociety',
            'priority': 15,
        })
        return True
