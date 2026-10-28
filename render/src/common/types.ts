export type Lang = 'fr' | 'en';

export type Brand = {
	name: string;
	accent: string; // couleur principale, ex. "#5B5BF7"
	accentInk?: string; // couleur du texte posé sur l'accent (défaut : blanc)
	handle?: string; // ex. "@habitudo"
	icon?: string; // chemin dans public/ (ex. "brands/habitudo/icon.png"), sinon initiale
	storeLine?: string; // ex. "Gratuit sur l'App Store et Google Play"
};

export type BaseProps = {
	lang: Lang;
	brand: Brand;
	cta: string;
	music?: string; // chemin dans public/, optionnel
};

export const FPS = 30;
export const WIDTH = 1080;
export const HEIGHT = 1920;

// Zones masquées par l'interface TikTok / Reels (approximations prudentes).
export const SAFE = {top: 170, bottom: 420, left: 64, right: 150};

export const t = (lang: Lang, fr: string, en: string) => (lang === 'fr' ? fr : en);
