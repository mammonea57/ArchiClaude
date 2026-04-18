# Guide — Premier projet

Ce guide décrit les étapes pour créer et analyser votre premier projet de faisabilité avec ArchiClaude.

---

## 1. Se connecter

1. Ouvrez http://localhost:3001 (ou l'URL de production).
2. Cliquez sur **Commencer** ou **Se connecter** depuis la page d'accueil.
3. Saisissez votre adresse e-mail et votre mot de passe.
4. Cliquez sur **Se connecter**.

Vous êtes redirigé vers la liste de vos projets.

---

## 2. Créer un projet

1. Depuis la page **Mes projets**, cliquez sur **Nouveau projet**.
2. Donnez un nom au projet (exemple : "Résidence Vincennes R+5").
3. Cliquez sur **Créer**.

Le projet est créé avec le statut **Brouillon**. Vous êtes redirigé vers la fiche projet.

---

## 3. Rechercher une adresse

1. Dans l'onglet **Parcelles**, tapez une adresse dans la barre de recherche.
   Exemple : `12 rue de la Paix, Paris 2`
2. Sélectionnez le résultat correspondant dans la liste de suggestions.
3. La carte se centre sur l'adresse choisie.

La recherche utilise la Base Adresse Nationale (BAN) — seules les adresses françaises sont prises en charge.

---

## 4. Sélectionner les parcelles

1. Cliquez sur une ou plusieurs parcelles cadastrales affichées sur la carte.
   Les parcelles sélectionnées apparaissent en surbrillance.
2. Vérifiez la référence cadastrale et la surface dans le panneau latéral.
3. Pour retirer une parcelle, cliquez à nouveau dessus.

Au moins une parcelle doit être sélectionnée pour continuer.

---

## 5. Remplir le brief

1. Dans l'onglet **Brief**, renseignez les paramètres du programme :
   - **Type de programme** (logements, bureaux, mixte, etc.)
   - **Nombre de logements cible** (indicatif)
   - **Surface de plancher souhaitée** (m²)
   - **Notes libres** — contraintes particulières, attentes, contexte
2. Cliquez sur **Enregistrer le brief**.

Ces informations orientent l'analyse de faisabilité. Vous pouvez les modifier à tout moment.

---

## 6. Analyser

1. Cliquez sur **Lancer l'analyse** (bouton bleu en haut de la fiche projet).
2. Un indicateur de progression s'affiche pendant l'analyse (environ 30 à 90 secondes).

L'analyse effectue automatiquement :
- Extraction des règles PLU (zonage, hauteur, emprise, CES/COS, reculs)
- Calcul des droits à construire
- Analyse du contexte de site (bruit, transports, voisinage)
- Recherche de jurisprudences et recours similaires
- Synthèse de faisabilité

---

## 7. Lire le rapport

Une fois l'analyse terminée, l'onglet **Rapport** devient accessible.

Le rapport contient :
- **Synthèse exécutive** — faisabilité globale, risques principaux
- **Règles PLU applicables** — tableau détaillé zone par zone
- **Droits à construire** — surface de plancher maximum, gabarit
- **Contexte de site** — nuisances sonores, desserte TC, voisinage
- **Versions** — historique des analyses successives avec comparaison

Chaque section affiche la source de la donnée et l'indice de confiance.

---

## 8. Exporter PDF

1. Depuis l'onglet **Rapport**, cliquez sur **Exporter PDF**.
2. Patientez quelques secondes pendant la génération du document.
3. Cliquez sur **Télécharger** quand le lien apparaît.

Le PDF inclut le cartouche de votre agence (logo, coordonnées, couleur) tel que configuré dans les [paramètres de l'agence](parametres-agence.md).

---

## Questions fréquentes

**La parcelle ne s'affiche pas sur la carte.**
Assurez-vous que l'adresse est bien localisée sur la carte avant de cliquer. Certaines parcelles de copropriété ne sont pas visibles à toutes les échelles — zoomez au maximum.

**L'analyse échoue avec une erreur PLU.**
Les règles PLU ne sont pas encore extraites pour toutes les communes. Vous pouvez déclencher l'extraction manuellement depuis l'onglet PLU ou contacter le support.

**Puis-je relancer une analyse après modification du brief ?**
Oui. Chaque lancement crée une nouvelle version du projet. Les versions sont comparables depuis l'onglet **Versions**.
