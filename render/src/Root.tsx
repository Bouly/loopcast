import React from 'react';
import {Composition, Still} from 'remotion';
import './common/fonts';
import {FPS, HEIGHT, WIDTH} from './common/types';
import {ChatStory, ChatStoryProps, chatTimeline} from './formats/ChatStory';
import {HookDemo, HookDemoProps, hookDemoTimeline} from './formats/HookDemo';
import {NotesApp, NotesAppProps, notesTimeline} from './formats/NotesApp';
import {Slideshow, SlideshowProps} from './formats/Slideshow';
import {Story, StoryProps, storyDemo, storyTimeline} from './formats/Story';

// Props de démonstration (utilisées dans le Studio Remotion : `npm run studio`).
const brand = {name: 'Habitudo', accent: '#5B5BF7', handle: '@habitudo'};

const notesDemo: NotesAppProps = {
	lang: 'fr',
	brand,
	cta: 'Teste Habitudo gratuitement',
	title: 'Ce qui a vraiment changé mes matins',
	items: ['Téléphone hors de la chambre', 'Un verre d’eau avant le café', '10 minutes de marche', 'Cocher mes habitudes dans Habitudo'],
};

const chatDemo: ChatStoryProps = {
	lang: 'fr',
	brand,
	cta: 'Lance ta série aujourd’hui',
	contactName: 'Léa',
	messages: [
		{from: 'them', text: 'T’as tenu ta résolution sport ?'},
		{from: 'me', text: 'Lol non, 3 jours 😅'},
		{from: 'them', text: 'Moi 41 jours d’affilée'},
		{from: 'me', text: 'Comment ???'},
		{from: 'them', text: 'J’utilise Habitudo, je coche chaque soir et je veux pas casser ma série'},
	],
};

const hookDemo: HookDemoProps = {
	lang: 'fr',
	brand,
	cta: 'Télécharge Habitudo',
	hook: 'Arrête de compter sur ta **motivation**',
	screens: [
		{caption: 'Choisis 3 habitudes, pas 15', mock: {kind: 'list', title: 'Aujourd’hui', items: [{label: 'Lire 10 pages', done: true}, {label: 'Marcher 20 min', done: true}, {label: 'Pas d’écran au lit'}]}},
		{caption: 'Coche-les chaque soir', mock: {kind: 'stat', title: 'Série', value: '21', label: 'jours d’affilée 🔥'}},
		{caption: 'Regarde-toi progresser', mock: {kind: 'chart', title: 'Cette semaine', bars: [0.3, 0.5, 0.45, 0.7, 0.8, 0.75, 1], labels: ['L', 'M', 'M', 'J', 'V', 'S', 'D']}},
	],
};

const slideshowDemo: SlideshowProps = {
	lang: 'fr',
	brand,
	cta: 'Commence ta série ce soir',
	slideIndex: 0,
	slides: [
		{title: '5 habitudes qui\nont changé\nma vie à 25 ans', emoji: '✨'},
		{title: 'Me lever à heure fixe', body: 'Même le week-end. Surtout le week-end.'},
		{title: 'Lire 10 pages par jour', body: '3 650 pages par an, sans effort.'},
	],
};

export const RemotionRoot: React.FC = () => (
	<>
		<Composition
			id="notes-app"
			component={NotesApp as React.FC<any>}
			fps={FPS}
			width={WIDTH}
			height={HEIGHT}
			durationInFrames={300}
			defaultProps={notesDemo}
			calculateMetadata={({props}) => ({durationInFrames: notesTimeline(props as NotesAppProps).total})}
		/>
		<Composition
			id="chat-story"
			component={ChatStory as React.FC<any>}
			fps={FPS}
			width={WIDTH}
			height={HEIGHT}
			durationInFrames={300}
			defaultProps={chatDemo}
			calculateMetadata={({props}) => ({durationInFrames: chatTimeline(props as ChatStoryProps).total})}
		/>
		<Composition
			id="hook-demo"
			component={HookDemo as React.FC<any>}
			fps={FPS}
			width={WIDTH}
			height={HEIGHT}
			durationInFrames={300}
			defaultProps={hookDemo}
			calculateMetadata={({props}) => ({durationInFrames: hookDemoTimeline(props as HookDemoProps).total})}
		/>
		<Still id="slideshow" component={Slideshow as React.FC<any>} width={WIDTH} height={HEIGHT} defaultProps={slideshowDemo} />
		<Composition
			id="story"
			component={Story as React.FC<any>}
			fps={FPS}
			width={WIDTH}
			height={HEIGHT}
			durationInFrames={300}
			defaultProps={storyDemo}
			calculateMetadata={({props}) => ({durationInFrames: storyTimeline(props as StoryProps).total})}
		/>
	</>
);
