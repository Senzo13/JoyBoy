// ===== EFFECTS - Stars, Comets =====

const STAR_COUNT = 180;
const DRIFT_SPEED = 0.008;    // % par frame (~0.5%/s à 60fps) — vitesse du voyage
const DRIFT_ANGLE = -0.12;    // ratio vertical (légèrement vers le haut)
const ROTATE_SPEED = 0.00003; // radians par frame — rotation lente du ciel

let starLayers = [];
let driftRAF = null;
let effectsInitialized = false;

function _populateStars(container) {
    const twinkleClasses = ['', 'tw-b', 'tw-c'];
    const data = [];

    for (let i = 0; i < STAR_COUNT; i++) {
        const star = document.createElement('div');
        const twClass = twinkleClasses[Math.floor(Math.random() * 3)];
        star.className = twClass ? 'star ' + twClass : 'star';

        const size = Math.random() * 2 + 1;
        const x = Math.random() * 100;
        const y = Math.random() * 100;
        const duration = Math.random() * 6 + 8;
        const delay = -(Math.random() * duration);
        const opacity = Math.random() * 0.3 + 0.7;
        const speed = DRIFT_SPEED * (0.5 + size / 3);

        star.style.cssText = `
            width: ${size}px;
            height: ${size}px;
            left: ${x}%;
            top: ${y}%;
            --duration: ${duration}s;
            --delay: ${delay}s;
            --opacity: ${opacity};
        `;

        container.appendChild(star);
        data.push({ el: star, x, y, speed });
    }
    return data;
}

function createStars() {
    const containers = [
        document.getElementById('stars'),
        document.getElementById('loading-stars'),
    ].filter(Boolean);

    if (!containers.length) return;

    if (driftRAF) {
        cancelAnimationFrame(driftRAF);
        driftRAF = null;
    }

    starLayers = containers.map((container) => {
        container.innerHTML = '';
        return {
            container,
            stars: _populateStars(container),
        };
    });

    startDrift();
}

function startDrift() {
    let last = performance.now();

    function drift(now) {
        let dt = (now - last) / 16.67;  // normaliser à 60fps
        last = now;
        if (dt > 3) dt = 1;  // ignorer les longues pauses (onglet en arrière-plan)
        const angle = ROTATE_SPEED * dt;
        const cos = Math.cos(angle);
        const sin = Math.sin(angle);

        for (let layerIndex = starLayers.length - 1; layerIndex >= 0; layerIndex--) {
            const layer = starLayers[layerIndex];
            if (!layer?.container?.isConnected) {
                starLayers.splice(layerIndex, 1);
                continue;
            }

            for (let i = 0; i < layer.stars.length; i++) {
                const s = layer.stars[i];

                // Rotation autour du centre (50%, 50%)
                const rx = s.x - 50;
                const ry = s.y - 50;
                s.x = 50 + rx * cos - ry * sin;
                s.y = 50 + rx * sin + ry * cos;

                // Drift vers la droite + léger vers le haut
                s.x += s.speed * dt;
                s.y += s.speed * DRIFT_ANGLE * dt;

                // Recyclage : sort à droite → réapparaît à gauche
                if (s.x > 102) {
                    s.x = -2;
                    s.y = Math.random() * 100;
                }
                // Recyclage vertical
                if (s.y < -2) s.y = 102;
                else if (s.y > 102) s.y = -2;

                s.el.style.left = s.x + '%';
                s.el.style.top = s.y + '%';
            }
        }

        driftRAF = starLayers.length ? requestAnimationFrame(drift) : null;
    }

    driftRAF = requestAnimationFrame(drift);
}

function createComet() {
    const container = document.getElementById('stars');
    if (!container) return;

    const comet = document.createElement('div');
    comet.className = 'comet';

    let startX, startY, endX, endY;
    const trajectory = Math.random();

    if (trajectory < 0.33) {
        startX = Math.random() * 20 + 10;
        startY = Math.random() * 15 + 5;
        endX = startX + 40 + Math.random() * 15;
        endY = startY + 40 + Math.random() * 20;
    } else if (trajectory < 0.5) {
        startX = Math.random() * 30 + 35;
        startY = Math.random() * 10 + 2;
        endX = startX + (Math.random() * 20 - 10);
        endY = startY + 50 + Math.random() * 20;
    } else {
        startX = Math.random() * 20 + 70;
        startY = Math.random() * 15 + 5;
        endX = startX - 45 - Math.random() * 15;
        endY = startY + 40 + Math.random() * 20;
    }

    const duration = Math.random() * 400 + 600;
    const angle = Math.atan2(endY - startY, endX - startX) * (180 / Math.PI);

    comet.style.cssText = `
        top: ${startY}%;
        left: ${startX}%;
        transform: rotate(${angle}deg);
        animation: comet-fall ${duration}ms linear forwards;
    `;

    container.appendChild(comet);

    const startTime = performance.now();
    function animateComet(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);

        const currentX = startX + (endX - startX) * progress;
        const currentY = startY + (endY - startY) * progress;

        comet.style.left = currentX + '%';
        comet.style.top = currentY + '%';

        if (progress < 1) {
            requestAnimationFrame(animateComet);
        } else {
            comet.remove();
        }
    }
    requestAnimationFrame(animateComet);
}

function scheduleComet() {
    const delay = Math.random() * 6000 + 4000;
    setTimeout(() => {
        createComet();
        scheduleComet();
    }, delay);
}

// Pirate Ship Lottie animation
function createPirateShip(forceFar = false) {
    const container = document.getElementById('stars');
    if (!container || typeof lottie === 'undefined') return;

    const ship = document.createElement('div');
    ship.className = 'pirate-ship';

    // Position de départ (gauche ou droite de l'écran)
    const fromLeft = Math.random() > 0.5;
    const startX = fromLeft ? -20 : 110;
    const endX = fromLeft ? 110 : -20;

    // 70% du temps: passage au centre (40-60% hauteur), 30%: plus varié
    let startY;
    if (Math.random() < 0.7) {
        // Passage centré horizontal
        startY = Math.random() * 20 + 40; // Entre 40% et 60%
    } else {
        // Passage plus varié
        startY = Math.random() * 50 + 15; // Entre 15% et 65%
    }
    const endY = startY + (Math.random() * 10 - 5); // Légère variation verticale

    // Durée du passage (3.5-5.5 secondes)
    const duration = Math.random() * 2000 + 3500;

    const flipX = fromLeft ? 1 : -1;
    const fromFar = forceFar || Math.random() < 0.4;
    ship.style.cssText = `
        left: ${startX}%;
        top: ${startY}%;
        --flip: ${flipX};
        animation: ${fromFar ? 'pirate-fade-far' : 'pirate-fade'} ${duration}ms ease-in-out forwards;
    `;

    container.appendChild(ship);

    // Charger l'animation Lottie
    const anim = lottie.loadAnimation({
        container: ship,
        renderer: 'svg',
        loop: true,
        autoplay: true,
        path: '/static/lottie/Pirate_Ship.json'
    });

    // Animer le déplacement
    const startTime = performance.now();
    function animateShip(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);

        // Easing pour un mouvement plus fluide
        const easeProgress = progress;
        const currentX = startX + (endX - startX) * easeProgress;
        const currentY = startY + (endY - startY) * easeProgress;

        ship.style.left = currentX + '%';
        ship.style.top = currentY + '%';

        if (progress < 1) {
            requestAnimationFrame(animateShip);
        } else {
            anim.destroy();
            ship.remove();
        }
    }
    requestAnimationFrame(animateShip);
}

function schedulePirateShip() {
    // Plus rare que la comète (15-30 secondes)
    const delay = Math.random() * 15000 + 15000;
    setTimeout(() => {
        createPirateShip();
        schedulePirateShip();
    }, delay);
}

function initEffects() {
    if (effectsInitialized) return;
    effectsInitialized = true;
    createStars();
    setTimeout(scheduleComet, Math.random() * 3000 + 2000);
    // Premier bateau pirate après 5 secondes (toujours de loin), puis schedule les suivants
    setTimeout(() => {
        createPirateShip(true);
        schedulePirateShip();
    }, 5000);
}
