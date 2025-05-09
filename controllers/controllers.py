from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)


class DzIntersocietyController(http.Controller):
    @http.route('/dz_intersociety_sync/status', type='json', auth='user')
    def get_sync_status(self):
        """Retourne l'état de synchronisation pour l'utilisateur actuel"""
        mappings = request.env['dz.company.mapping'].search([
            '|',
            ('source_company_id', '=', request.env.company.id),
            ('target_company_id', '=', request.env.company.id)
        ])

        if not mappings:
            return {
                'status': 'not_configured',
                'message': 'Aucune configuration de synchronisation trouvée'
            }

        # Vérifier les statistiques de synchronisation
        stats = {
            'partners': {
                'total': request.env['res.partner'].search_count([('company_id', '=', request.env.company.id)]),
                'synced': request.env['res.partner'].search_count([
                    ('company_id', '=', request.env.company.id),
                    ('is_synced', '=', True)
                ])
            },
            'products': {
                'total': request.env['product.template'].search_count([('company_id', '=', request.env.company.id)]),
                'synced': request.env['product.template'].search_count([
                    ('company_id', '=', request.env.company.id),
                    ('is_synced', '=', True)
                ])
            },
            'invoices': {
                'total': request.env['account.move'].search_count([
                    ('company_id', '=', request.env.company.id),
                    ('move_type', 'in', ['out_invoice', 'in_invoice']),
                    ('state', '=', 'posted')
                ]),
                'synced': request.env['account.move'].search_count([
                    ('company_id', '=', request.env.company.id),
                    ('move_type', 'in', ['out_invoice', 'in_invoice']),
                    ('state', '=', 'posted'),
                    ('is_synced', '=', True)
                ])
            },
            'purchases': {
                'total': request.env['purchase.order'].search_count([
                    ('company_id', '=', request.env.company.id),
                    ('state', 'in', ['purchase', 'done'])
                ]),
                'synced': request.env['purchase.order'].search_count([
                    ('company_id', '=', request.env.company.id),
                    ('state', 'in', ['purchase', 'done']),
                    ('is_synced', '=', True)
                ])
            }
        }

        return {
            'status': 'configured',
            'mappings': [{
                'id': m.id,
                'name': m.name,
                'source_company': m.source_company_id.name,
                'target_company': m.target_company_id.name,
                'last_sync': m.last_sync_date,
                'auto_sync': m.auto_sync
            } for m in mappings],
            'stats': stats
        }

    @http.route('/dz_intersociety_sync/dashboard', auth='user')
    def dashboard(self):
        """Page dashboard de synchronisation"""
        mappings = request.env['dz.company.mapping'].search([
            '|',
            ('source_company_id', '=', request.env.company.id),
            ('target_company_id', '=', request.env.company.id)
        ])

        # Récupérer l'ID de l'action pour l'assistant de synchronisation
        action_id = request.env.ref('dz_intersociety_sync.action_dz_sync_wizard', raise_if_not_found=False)
        action_id = action_id.id if action_id else 0

        return request.render('dz_intersociety_sync.dashboard_template', {
            'mappings': mappings,
            'company': request.env.company,
            'action_id': action_id
        })

    @http.route('/dz_intersociety_sync/trigger_sync', type='json', auth='user')
    def trigger_sync(self, mapping_id=None):
        """Déclenche une synchronisation manuelle"""
        if not mapping_id:
            return {'error': 'Aucun mappage spécifié'}

        mapping = request.env['dz.company.mapping'].browse(int(mapping_id))
        if not mapping.exists():
            return {'error': 'Mappage non trouvé'}

        try:
            # Créer et ouvrir l'assistant de synchronisation
            wizard = request.env['dz.sync.wizard'].create({
                'mapping_id': mapping.id,
                'sync_partners': mapping.sync_partners,
                'sync_products': mapping.sync_products,
                'sync_invoices': mapping.sync_invoices,
                'sync_sales': mapping.sync_sales,
                'sync_purchases': mapping.sync_purchases,
            })

            # Retourner l'ID du wizard pour redirection
            return {
                'status': 'success',
                'wizard_id': wizard.id,
                'action': 'dz_intersociety_sync.action_dz_sync_wizard'
            }
        except Exception as e:
            _logger.error("Erreur lors du déclenchement de la synchronisation: %s", str(e))
            return {'error': str(e)}

    def _get_sync_wizard_action_id(self):
        """Récupère l'ID de l'action pour l'assistant de synchronisation"""
        action = self.env.ref('dz_intersociety_sync.action_dz_sync_wizard', raise_if_not_found=False)
        return action.id if action else 0
