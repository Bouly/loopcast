import {continueRender, delayRender, staticFile} from 'remotion';

export const FONT = `'Inter', 'Apple Color Emoji', 'Noto Color Emoji', 'Segoe UI Emoji', sans-serif`;

const WEIGHTS: Record<string, string> = {
	'400': 'Inter-Regular.otf',
	'500': 'Inter-Medium.otf',
	'600': 'Inter-SemiBold.otf',
	'700': 'Inter-Bold.otf',
	'800': 'Inter-ExtraBold.otf',
	'900': 'Inter-Black.otf',
};

// Chargé une seule fois au niveau module : le rendu attend que les polices soient prêtes.
if (typeof document !== 'undefined') {
	const handle = delayRender('Chargement des polices Inter');
	Promise.all(
		Object.entries(WEIGHTS).map(([weight, file]) => {
			const face = new FontFace('Inter', `url(${staticFile(`fonts/${file}`)})`, {weight});
			document.fonts.add(face);
			return face.load();
		}),
	)
		.then(() => continueRender(handle))
		.catch((err) => {
			console.error('Polices non chargées', err);
			continueRender(handle);
		});
}
