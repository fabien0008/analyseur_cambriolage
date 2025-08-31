#!/usr/bin/env python3
"""
Analyseur de Cambriolages - Interface Textuel Interactive (TUI)
Utilise Textual pour une interface moderne en terminal
"""

import asyncio
import geopandas as gpd
import pandas as pd
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
from shapely.geometry import Point
import re
import time
from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import (
    Header, Footer, Input, Button, Static, DataTable, ProgressBar, 
    TextArea, TabbedContent, TabPane, Label, Tree
)
from textual.reactive import reactive
from rich.text import Text
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.console import Console

class CambriolageAnalyzer:
    def __init__(self):
        self.geolocator = Nominatim(user_agent="analyseur_tui_v1", timeout=10)
        self.donnees_annuelles = {}
        self.donnees_completes = None
        self.unites_urbaines = None
        self.loaded = False
    
    async def charger_donnees(self, progress_callback=None):
        """Charge les données de façon asynchrone"""
        annees = ['2019', '2020', '2021', '2022']
        total = len(annees)
        
        for i, annee in enumerate(annees):
            try:
                if progress_callback:
                    await progress_callback(i, total, f"Chargement {annee}...")
                
                fichier = f"cambriolageslogementsechelleinfracommunale.{annee}.shp"
                gdf = gpd.read_file(fichier)
                self.donnees_annuelles[annee] = gdf
                
                # Petit délai pour permettre à l'UI de se rafraîchir
                await asyncio.sleep(0.1)
                
            except Exception as e:
                if progress_callback:
                    await progress_callback(i, total, f"Erreur {annee}: {str(e)[:30]}")
                continue
        
        # Combiner les données
        if self.donnees_annuelles:
            all_data = list(self.donnees_annuelles.values())
            self.donnees_completes = pd.concat(all_data, ignore_index=True)
            self.unites_urbaines = self.donnees_completes[['code_uu', 'libelle_uu']].drop_duplicates()
            self.loaded = True
            
        if progress_callback:
            await progress_callback(total, total, "Données chargées !")
    
    async def geocoder_adresse(self, adresse):
        """Géocode une adresse de façon asynchrone"""
        try:
            loop = asyncio.get_event_loop()
            location = await loop.run_in_executor(None, self.geolocator.geocode, adresse + ", France")
            
            if location:
                return location.latitude, location.longitude, location.address
            return None, None, None
            
        except Exception as e:
            return None, None, str(e)
    
    def analyser_zone_dans_polygone(self, lat, lon):
        """Trouve les zones exactes contenant le point"""
        if not self.loaded:
            return []
            
        point_recherche = Point(lon, lat)
        zones_trouvees = []
        
        for annee, gdf in self.donnees_annuelles.items():
            try:
                mask = gdf.geometry.contains(point_recherche)
                zones_dans_polygone = gdf[mask]
                
                for _, zone in zones_dans_polygone.iterrows():
                    zones_trouvees.append({
                        'annee': annee,
                        'code_uu': zone['code_uu'],
                        'libelle_uu': zone['libelle_uu'],
                        'classe': zone['classe'],
                        'risque_num': self.extraire_valeur_numerique(zone['classe'])
                    })
            except:
                continue
        
        return zones_trouvees
    
    def trouver_unites_urbaines_proches(self, lat, lon, distance_max=50):
        """Trouve les UU proches du point"""
        if not self.loaded:
            return []
            
        point_recherche = Point(lon, lat)
        resultats = []
        
        # Utiliser une année comme échantillon
        sample_data = self.donnees_annuelles.get('2022', list(self.donnees_annuelles.values())[0])
        
        for _, row in sample_data.iterrows():
            try:
                centroid = row.geometry.centroid
                distance = geodesic((lat, lon), (centroid.y, centroid.x)).kilometers
                
                if distance <= distance_max:
                    resultats.append({
                        'code_uu': row['code_uu'],
                        'libelle_uu': row['libelle_uu'],
                        'distance_km': distance
                    })
            except:
                continue
        
        # Supprimer doublons et trier
        df_resultats = pd.DataFrame(resultats).drop_duplicates(subset=['code_uu']).sort_values('distance_km')
        return df_resultats.to_dict('records')
    
    def analyser_unite_urbaine(self, code_uu):
        """Analyse complète d'une UU"""
        if not self.loaded:
            return None
            
        donnees_uu = self.donnees_completes[self.donnees_completes['code_uu'] == code_uu]
        
        if donnees_uu.empty:
            return None
        
        analyse_par_annee = {}
        zones_a_risque = []
        
        for annee in ['2019', '2020', '2021', '2022']:
            donnees_annee = donnees_uu[donnees_uu['annee'] == annee]
            
            if donnees_annee.empty:
                continue
                
            # Classification par risque
            risque_faible = len(donnees_annee[donnees_annee['classe'].str.contains('moins de', case=False, na=False)])
            risque_eleve = len(donnees_annee[donnees_annee['classe'].str.contains('plus de', case=False, na=False)])
            risque_moyen = len(donnees_annee) - risque_faible - risque_eleve
            
            analyse_par_annee[annee] = {
                'total': len(donnees_annee),
                'faible': risque_faible,
                'moyen': risque_moyen,
                'eleve': risque_eleve,
                'classes': list(donnees_annee['classe'].unique())
            }
            
            # Zones dangereuses
            zones_danger = donnees_annee[
                donnees_annee['classe'].str.contains('plus de|de [1-9][0-9]', case=False, na=False, regex=True)
            ]
            
            for _, zone in zones_danger.iterrows():
                zones_a_risque.append({
                    'annee': zone['annee'],
                    'classe': zone['classe'],
                    'risque_num': self.extraire_valeur_numerique(zone['classe'])
                })
        
        return {
            'code_uu': code_uu,
            'libelle_uu': donnees_uu.iloc[0]['libelle_uu'],
            'analyse_par_annee': analyse_par_annee,
            'zones_a_risque': zones_a_risque
        }
    
    def extraire_valeur_numerique(self, classe):
        """Convertit une classe en valeur numérique"""
        try:
            if 'moins de' in classe:
                match = re.search(r'moins de (\d+(?:,\d+)?)', classe)
                if match:
                    return float(match.group(1).replace(',', '.'))
            elif 'plus de' in classe:
                match = re.search(r'plus de (\d+(?:,\d+)?)', classe)
                if match:
                    return float(match.group(1).replace(',', '.'))
            elif 'de ' in classe and ' à ' in classe:
                match = re.search(r'de (\d+(?:,\d+)?) à (\d+(?:,\d+)?)', classe)
                if match:
                    val1 = float(match.group(1).replace(',', '.'))
                    val2 = float(match.group(2).replace(',', '.'))
                    return (val1 + val2) / 2
        except:
            pass
        return 0

class CambriolageApp(App):
    """Application Textual pour l'analyse des cambriolages"""
    
    CSS_PATH = None
    CSS = """
    .title {
        dock: top;
        height: 3;
        background: $boost;
        color: $text;
        text-align: center;
        content-align: center middle;
    }
    
    .search-box {
        dock: top;
        height: 5;
        background: $surface;
        padding: 1;
    }
    
    .results {
        scrollbar-gutter: stable;
    }
    
    .status-bar {
        dock: bottom;
        height: 3;
        background: $primary;
        color: $text;
    }
    
    .loading {
        background: $warning;
        color: $text;
        text-align: center;
        padding: 1;
    }
    
    .error {
        background: $error;
        color: $text;
        padding: 1;
    }
    
    .success {
        background: $success;
        color: $text;
        padding: 1;
    }
    
    .risk-high {
        background: $error;
        color: $text;
    }
    
    .risk-medium {
        background: $warning;
        color: $text;
    }
    
    .risk-low {
        background: $success;
        color: $text;
    }
    """
    
    def __init__(self):
        super().__init__()
        self.analyzer = CambriolageAnalyzer()
        self.current_results = None
    
    def compose(self) -> ComposeResult:
        """Crée l'interface utilisateur"""
        yield Header()
        
        with Vertical():
            yield Static("🏠 ANALYSEUR DE CAMBRIOLAGES - DONNÉES GÉOGRAPHIQUES PRÉCISES", classes="title")
            
            with Container(classes="search-box"):
                yield Input(placeholder="Entrez une adresse (ex: 10 rue de la République, 69002 Lyon)", id="address-input")
                with Horizontal():
                    yield Button("🔍 Analyser", variant="primary", id="analyze-btn")
                    yield Button("📋 Lister les villes", variant="default", id="list-btn")
                    yield Button("ℹ️  Aide", variant="default", id="help-btn")
            
            with TabbedContent():
                with TabPane("🎯 Résultats", id="results-tab"):
                    yield ScrollableContainer(
                        Static("Entrez une adresse pour commencer l'analyse", id="results-content"),
                        classes="results"
                    )
                
                with TabPane("📊 Statistiques", id="stats-tab"):
                    yield ScrollableContainer(
                        Static("Statistiques apparaîtront ici après une recherche", id="stats-content"),
                        classes="results"
                    )
                
                with TabPane("🗺️  Villes", id="cities-tab"):
                    yield ScrollableContainer(
                        Static("Chargement de la liste des villes...", id="cities-content"),
                        classes="results"
                    )
        
        yield Footer()
    
    async def on_mount(self) -> None:
        """Initialisation de l'application"""
        self.title = "Analyseur de Cambriolages"
        self.sub_title = "Interface moderne en terminal"
        
        # Charger les données au démarrage
        await self.charger_donnees_initiales()
    
    async def charger_donnees_initiales(self):
        """Charge les données au démarrage avec indicateur de progression"""
        results_widget = self.query_one("#results-content")
        results_widget.update("🔄 Chargement des données géographiques en cours...\n\nCela peut prendre quelques secondes...")
        
        async def progress_callback(current, total, message):
            progress_text = f"🔄 Chargement des données: {current}/{total}\n{message}\n\n"
            if current < total:
                progress_text += "▋" * (current * 20 // total) + "░" * (20 - current * 20 // total)
            else:
                progress_text += "▋" * 20 + " ✅ Terminé!"
            results_widget.update(progress_text)
        
        await self.analyzer.charger_donnees(progress_callback)
        
        if self.analyzer.loaded:
            nb_zones = len(self.analyzer.donnees_completes)
            nb_uu = len(self.analyzer.unites_urbaines)
            
            results_widget.update(
                f"✅ Données chargées avec succès!\n\n"
                f"📊 {nb_zones:,} zones géographiques disponibles\n"
                f"🏙️  {nb_uu} unités urbaines\n"
                f"📅 Période: 2019-2022\n\n"
                f"💡 Entrez une adresse pour commencer l'analyse"
            )
            
            # Remplir la liste des villes
            await self.remplir_liste_villes()
        else:
            results_widget.update("❌ Erreur lors du chargement des données.\nVérifiez que les fichiers .shp sont présents.")
    
    async def remplir_liste_villes(self):
        """Remplit l'onglet des villes"""
        cities_widget = self.query_one("#cities-content")
        
        if not self.analyzer.loaded:
            cities_widget.update("❌ Données non chargées")
            return
        
        villes_text = "🏙️  UNITÉS URBAINES DISPONIBLES\n\n"
        
        for i, row in self.analyzer.unites_urbaines.iterrows():
            villes_text += f"{i+1:3d}. {row['libelle_uu']} ({row['code_uu']})\n"
        
        cities_widget.update(villes_text)
    
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Gestion des clics sur les boutons"""
        if event.button.id == "analyze-btn":
            await self.analyser_adresse()
        elif event.button.id == "list-btn":
            # Basculer vers l'onglet des villes
            tabbed = self.query_one(TabbedContent)
            tabbed.active = "cities-tab"
        elif event.button.id == "help-btn":
            await self.afficher_aide()
    
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Gestion de l'appui sur Entrée dans le champ d'adresse"""
        if event.input.id == "address-input":
            await self.analyser_adresse()
    
    async def analyser_adresse(self):
        """Analyse l'adresse saisie"""
        if not self.analyzer.loaded:
            self.query_one("#results-content").update("❌ Données non chargées")
            return
        
        address_input = self.query_one("#address-input")
        adresse = address_input.value.strip()
        
        if not adresse:
            self.query_one("#results-content").update("⚠️  Veuillez entrer une adresse")
            return
        
        results_widget = self.query_one("#results-content")
        results_widget.update(f"🔍 Géolocalisation de: {adresse}\n\n⏳ Recherche en cours...")
        
        # Géocodage
        lat, lon, adresse_complete = await self.analyzer.geocoder_adresse(adresse)
        
        if lat is None:
            results_widget.update(f"❌ Adresse introuvable: {adresse}\n\nEssayez avec une adresse plus précise.")
            return
        
        results_widget.update(
            f"✅ Position trouvée!\n\n"
            f"📍 {adresse_complete}\n"
            f"🌐 Coordonnées: {lat:.6f}, {lon:.6f}\n\n"
            f"🔍 Analyse des zones de cambriolage..."
        )
        
        # Analyse des zones exactes
        zones_exactes = self.analyzer.analyser_zone_dans_polygone(lat, lon)
        
        # Recherche des UU proches
        uu_proches = self.analyzer.trouver_unites_urbaines_proches(lat, lon)
        
        # Construire les résultats
        resultats_text = f"📍 RÉSULTATS POUR: {adresse}\n"
        resultats_text += f"🌐 {adresse_complete}\n"
        resultats_text += "═" * 60 + "\n\n"
        
        # Zones exactes
        if zones_exactes:
            resultats_text += "🎯 LOCALISATION PRÉCISE TROUVÉE!\n\n"
            
            # Extraire la ville de l'adresse géocodée pour clarification
            ville_detectee = "Ville inconnue"
            if adresse_complete:
                parts = adresse_complete.split(', ')
                for part in parts:
                    # Chercher une ville française typique
                    if any(keyword in part.lower() for keyword in ['saint-', 'sainte-']) or \
                       any(part.lower().endswith(suffix) for suffix in ['-sur-', '-les-', '-en-']):
                        ville_detectee = part
                        break
                    # Si pas de pattern spécial, prendre le 3ème élément (souvent la ville)
                    elif len(parts) >= 3 and part != parts[0] and part != parts[1]:
                        ville_detectee = part
                        break
            
            for zone in zones_exactes:
                risque_num = zone['risque_num']
                
                if risque_num > 10:
                    emoji, niveau = "🔴", "ÉLEVÉ"
                elif risque_num > 5:
                    emoji, niveau = "🟡", "MOYEN"  
                else:
                    emoji, niveau = "🟢", "FAIBLE"
                
                # Affichage amélioré avec clarification
                if zone['libelle_uu'] == "Paris" and "saint" in ville_detectee.lower():
                    resultats_text += f"📊 Zone dans l'Unité Urbaine de {zone['libelle_uu']} ({zone['annee']}):\n"
                    resultats_text += f"   ℹ️  Note: {ville_detectee} fait partie de l'agglomération parisienne\n"
                else:
                    resultats_text += f"📊 {zone['libelle_uu']} ({zone['annee']}):\n"
                
                resultats_text += f"   • Classe de cambriolage: {zone['classe']}\n"
                resultats_text += f"   • Niveau de risque: {emoji} {niveau} ({risque_num:.1f} pour 1000 logements)\n\n"
        
        # UU proches
        if uu_proches:
            resultats_text += f"🗺️  UNITÉS URBAINES PROCHES ({len(uu_proches)} trouvée(s)):\n\n"
            
            for i, uu in enumerate(uu_proches[:5]):
                resultats_text += f"{i+1}. {uu['libelle_uu']} (à {uu['distance_km']:.1f}km)\n"
                
                # Analyse de cette UU
                analyse = self.analyzer.analyser_unite_urbaine(uu['code_uu'])
                
                if analyse:
                    # Stats récentes
                    if '2022' in analyse['analyse_par_annee']:
                        stats_2022 = analyse['analyse_par_annee']['2022']
                        total = stats_2022['total']
                        
                        if total > 0:
                            faible_pct = stats_2022['faible'] * 100 // total
                            eleve_pct = stats_2022['eleve'] * 100 // total
                            moyen_pct = 100 - faible_pct - eleve_pct
                            
                            resultats_text += f"   2022: 🟢{faible_pct}% faible | 🟡{moyen_pct}% moyen | 🔴{eleve_pct}% élevé\n"
                
                resultats_text += "\n"
        else:
            resultats_text += "❌ Aucune unité urbaine trouvée dans un rayon de 50km\n"
        
        results_widget.update(resultats_text)
        
        # Remplir l'onglet statistiques
        await self.remplir_statistiques(uu_proches)
        
        self.current_results = {
            'adresse': adresse,
            'coordonnees': (lat, lon),
            'zones_exactes': zones_exactes,
            'uu_proches': uu_proches
        }
    
    async def remplir_statistiques(self, uu_proches):
        """Remplit l'onglet statistiques"""
        stats_widget = self.query_one("#stats-content")
        
        if not uu_proches:
            stats_widget.update("📊 Aucune statistique disponible")
            return
        
        stats_text = "📊 STATISTIQUES DÉTAILLÉES\n\n"
        
        for uu in uu_proches[:3]:  # Top 3
            analyse = self.analyzer.analyser_unite_urbaine(uu['code_uu'])
            
            if not analyse:
                continue
            
            stats_text += f"🏙️  {uu['libelle_uu'].upper()}\n"
            stats_text += "─" * 40 + "\n"
            
            # Évolution par année
            for annee in ['2019', '2020', '2021', '2022']:
                if annee in analyse['analyse_par_annee']:
                    stats = analyse['analyse_par_annee'][annee]
                    total = stats['total']
                    
                    if total > 0:
                        faible_pct = stats['faible'] * 100 // total
                        eleve_pct = stats['eleve'] * 100 // total
                        moyen_pct = 100 - faible_pct - eleve_pct
                        
                        stats_text += f"{annee}: {total:2d} zones - "
                        stats_text += f"🟢{faible_pct:2d}% 🟡{moyen_pct:2d}% 🔴{eleve_pct:2d}%\n"
            
            # Zones à risque
            zones_risque_recentes = [
                z for z in analyse['zones_a_risque'] 
                if z['annee'] in ['2021', '2022']
            ]
            
            if zones_risque_recentes:
                stats_text += f"\n⚠️  Zones à risque élevé (2021-2022):\n"
                for zone in zones_risque_recentes[:3]:
                    stats_text += f"   • {zone['annee']}: {zone['classe']}\n"
            
            stats_text += "\n"
        
        stats_widget.update(stats_text)
    
    async def afficher_aide(self):
        """Affiche l'aide"""
        aide_text = """
ℹ️  AIDE - ANALYSEUR DE CAMBRIOLAGES

🎯 FONCTIONNALITÉS:
• Géolocalisation précise d'adresses
• Analyse des taux de cambriolages par zone
• Données géographiques infracommunales
• Évolution temporelle 2019-2022

🔍 UTILISATION:
1. Entrez une adresse française dans le champ
2. Cliquez sur "Analyser" ou appuyez sur Entrée
3. Consultez les résultats dans les différents onglets

🏙️  UNITÉS URBAINES (UU):
Les données sont organisées par Unités Urbaines qui regroupent
les agglomérations urbaines continues. Par exemple:
• Saint-Ouen fait partie de l'UU "Paris"
• Boulogne-Billancourt fait partie de l'UU "Paris"
• C'est normal et conforme aux définitions INSEE

📊 NIVEAUX DE RISQUE:
🟢 FAIBLE: Taux < 5 cambriolages/1000 logements
🟡 MOYEN: Taux 5-10 cambriolages/1000 logements  
🔴 ÉLEVÉ: Taux > 10 cambriolages/1000 logements

🗂️  ONGLETS:
• Résultats: Analyse principale
• Statistiques: Données détaillées par ville
• Villes: Liste des unités urbaines disponibles

⚡ RACCOURCIS:
• Entrée: Lancer l'analyse
• Ctrl+C: Quitter l'application

📅 Source des données:
Service statistique ministériel de la sécurité intérieure (SSMSI)
Période: 2019-2022 • Granularité: Infracommunale
        """
        
        self.query_one("#results-content").update(aide_text)

def main():
    """Point d'entrée principal"""
    app = CambriolageApp()
    app.run()

if __name__ == "__main__":
    main()