/** @odoo-module **/

import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { KanbanRenderer } from "@web/views/kanban/kanban_renderer";
import { useService } from "@web/core/utils/hooks";
import { useState, onWillStart, onMounted } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";

/**
 * Contrôleur pour le tableau de bord de synchronisation inter-sociétés
 * Étend le contrôleur Kanban standard pour ajouter des fonctionnalités spécifiques
 */
class DzSyncDashboardController extends KanbanController {
    setup() {
        super.setup();
        this.rpc = useService("rpc");
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");

        this.state = useState({
            syncStats: null,
            syncInProgress: false,
            mappings: [],
            lastUpdate: new Date(),
        });

        onWillStart(async () => {
            await this.loadDashboardData();
        });

        onMounted(() => {
            // Rafraîchir les statistiques toutes les 5 minutes
            this.interval = browser.setInterval(() => {
                this.loadDashboardData();
            }, 5 * 60 * 1000);
        });
    }

    /**
     * Nettoie l'intervalle lorsque le composant est détruit
     */
    onWillUnmount() {
        if (this.interval) {
            browser.clearInterval(this.interval);
        }
    }

    /**
     * Charge les données du tableau de bord depuis le serveur
     */
    async loadDashboardData() {
        try {
            const result = await this.rpc("/dz_intersociety_sync/status");
            if (result.status === "configured") {
                this.state.syncStats = result.stats;
                this.state.mappings = result.mappings;
            } else {
                this.state.syncStats = null;
                this.state.mappings = [];
            }
            this.state.lastUpdate = new Date();
        } catch (error) {
            this.notification.add(
                this.env._t("Erreur lors du chargement des statistiques de synchronisation"),
                { type: "danger" }
            );
            console.error("Erreur du tableau de bord:", error);
        }
    }

    /**
     * Déclenche une synchronisation manuelle pour un mappage spécifique
     * @param {Number} mappingId - ID du mappage à synchroniser
     */
    async triggerSync(mappingId) {
        this.state.syncInProgress = true;
        try {
            const result = await this.rpc("/dz_intersociety_sync/trigger_sync", {
                mapping_id: mappingId,
            });

            if (result.error) {
                this.notification.add(result.error, { type: "danger" });
            } else if (result.wizard_id) {
                // Ouvrir l'assistant de synchronisation
                this.action.doAction({
                    type: "ir.actions.act_window",
                    res_model: "dz.sync.wizard",
                    res_id: result.wizard_id,
                    views: [[false, "form"]],
                    target: "new",
                    context: { create: false },
                });
            }

            // Mettre à jour les données après une synchronisation
            await this.loadDashboardData();
        } catch (error) {
            this.notification.add(
                this.env._t("Erreur lors du déclenchement de la synchronisation"),
                { type: "danger" }
            );
            console.error("Erreur de synchronisation:", error);
        } finally {
            this.state.syncInProgress = false;
        }
    }

    /**
     * Ouvre la vue de configuration des mappages
     */
    openMappingConfiguration() {
        this.action.doAction("dz_intersociety_sync.action_dz_company_mapping");
    }

    /**
     * Ouvre l'assistant de synchronisation manuelle
     */
    openSyncWizard() {
        this.action.doAction("dz_intersociety_sync.action_dz_sync_wizard");
    }

    /**
     * Formate une date pour l'affichage dans l'interface
     * @param {String} dateString - Date au format string
     * @returns {String} - Date formatée
     */
    formatDate(dateString) {
        if (!dateString) return this.env._t("Jamais");

        const date = new Date(dateString);
        return date.toLocaleString(this.env.lang || "fr-FR", {
            day: "2-digit",
            month: "2-digit",
            year: "numeric",
            hour: "2-digit",
            minute: "2-digit",
        });
    }

    /**
     * Calcule le pourcentage de synchronisation
     * @param {Object} stats - Statistiques pour un type d'objet
     * @returns {Number} - Pourcentage
     */
    calculatePercentage(stats) {
        if (!stats || !stats.total || stats.total === 0) return 0;
        return Math.round((stats.synced / stats.total) * 100);
    }
}

/**
 * Renderer pour le tableau de bord de synchronisation inter-sociétés
 * Utilise un template QWeb personnalisé
 */
class DzSyncDashboardRenderer extends KanbanRenderer {
    setup() {
        super.setup();
    }
}

/**
 * Enregistre la vue tableau de bord personnalisée
 */
registry.category("views").add("dz_sync_dashboard", {
    ...kanbanView,
    Controller: DzSyncDashboardController,
    Renderer: DzSyncDashboardRenderer,
    buttonTemplate: "dz_intersociety_sync.DashboardButtons",
});

export default {
    DzSyncDashboardController,
    DzSyncDashboardRenderer,
};
