{
    'name': 'Inter-Society Synchronization',
    'version': '1.0',
    'summary': 'Synchronisation automatique entre sociétés',
    'description': """
        Module de synchronisation automatique des transactions entre deux sociétés:
        - Société principale: toutes les opérations (facturées et non facturées)
        - Société secondaire: uniquement les opérations facturées

        Développé spécifiquement pour le contexte algérien.
    """,
    'category': 'Accounting/Accounting',
    'author': 'SARL Litmed Pro',
    'website': 'https://www.litmedpro.dz',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'account',
        'sale_management',
        'purchase',
        'stock',
        'l10n_dz',  # Module de localisation algérienne
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',

        'data/ir_config_parameter.xml',
        'data/action_data.xml',
        'data/stock_data.xml',
        'data/sequence_data.xml',

        'views/company_mapping_views.xml',
        'views/account_views.xml',
        'views/sale_views.xml',
        'views/purchase_views.xml',
        'views/menu_views.xml',
        'views/dashboard_template.xml',
        'views/partner_views.xml',

        'wizards/sync_wizard.xml',
        'wizards/export_wizard.xml',
    ],
    'images': ['static/description/icon.png'],
    'assets': {
        'web.assets_backend': [
            'dz_intersociety_sync/static/src/scss/style.scss',
            'dz_intersociety_sync/static/src/js/dashboard.js',
        ],
        'web.assets_qweb': [
            'dz_intersociety_sync/static/src/xml/dashboard.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
