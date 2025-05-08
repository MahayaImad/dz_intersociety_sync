{
    'name': 'Litmed Inter-Society Synchronization',
    'version': '1.0',
    'summary': 'Synchronisation automatique entre sociétés pour SARL Litmed Pro',
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
        'views/company_mapping_views.xml',
        'views/account_views.xml',
        'views/sale_views.xml',
        'views/purchase_views.xml',
        'views/menu_views.xml',
        'data/ir_config_parameter.xml',
        'wizards/sync_wizard.xml',
    ],
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
}
