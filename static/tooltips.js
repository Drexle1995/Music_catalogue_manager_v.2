/**
 * tooltips.js — Tooltip-Sichtbarkeits-Toggle und Viewport-sichere Positionierung.
 *
 * Warum position:fixed statt CSS ::after:
 *   CSS-Pseudoelemente mit position:absolute werden von overflow:scroll-Eltern
 *   abgeschnitten (scrollbare Sidebar). Eine einzige position:fixed Blase
 *   direkt im <body> umgeht dieses Problem vollstaendig.
 *
 * Ablauf:
 *   1. _blasenErstellen(): haengt #tt-blase einmalig an <body>.
 *   2. _eventsStarten(): Event-Delegation auf document (Capture-Phase).
 *   3. _zeigen(el): setzt Text, misst Abmessungen, berechnet Position,
 *      kippt nach unten bei Platzmangel, begrenzt horizontal, richtet Pfeil aus.
 *   4. _verbergen(): blendet Blase aus.
 *
 * Toggle-Zustand wird in localStorage gespeichert (Schluessel: sbs_tooltips_visible).
 */

(function () {
  'use strict';

  var LS_KEY   = 'sbs_tooltips_visible';
  var BTN_ID   = 'btnTooltipToggle';
  var TT_CLASS = 'tooltips-hidden';
  var BLASE_ID = 'tt-blase';

  /* Mindestabstand zum Viewport-Rand in Pixeln (links, rechts, oben, unten). */
  var RAND = 8;
  /* Abstand zwischen Pfeilspitze und Elementkante in Pixeln. */
  var PFEIL_ABSTAND = 12;

  /* ── Sichtbarkeits-Toggle ─────────────────────────────────────────────── */

  /* Gespeicherter Zustand laden — Standard ist AN (true). */
  function _istSichtbar() {
    var val = localStorage.getItem(LS_KEY);
    return val === null ? true : val === 'true';
  }

  /* body-Klasse und Button-Label synchronisieren. */
  function _anwenden(sichtbar) {
    if (sichtbar) {
      document.body.classList.remove(TT_CLASS);
    } else {
      document.body.classList.add(TT_CLASS);
    }

    var btn = document.getElementById(BTN_ID);
    if (btn) {
      if (sichtbar) {
        btn.textContent = '? Hilfe AN';
        btn.classList.add('tt-an');
        btn.title = 'Tooltips ausschalten';
      } else {
        btn.textContent = '? Hilfe AUS';
        btn.classList.remove('tt-an');
        btn.title = 'Tooltips einschalten';
      }
    }
  }

  /* Zustand umschalten, speichern und aktiven Tooltip sofort ausblenden. */
  function _umschalten() {
    var neu = !_istSichtbar();
    localStorage.setItem(LS_KEY, String(neu));
    _anwenden(neu);
    if (!neu) { _verbergen(); }
  }

  /* ── Tooltip-Blase ────────────────────────────────────────────────────── */

  var _blase = null;

  /* Erstellt einmalig das Tooltip-DOM-Element und haengt es an <body>. */
  function _blasenErstellen() {
    var el = document.createElement('div');
    el.id = BLASE_ID;
    document.body.appendChild(el);
    return el;
  }

  /* Blendet die Blase aus und setzt Zustand zurueck. */
  function _verbergen() {
    if (!_blase) { return; }
    _blase.style.display = 'none';
    _blase.classList.remove('tt-unten');
  }

  /**
   * Zeigt die Tooltip-Blase fuer ein [data-tooltip]-Element an.
   *
   * Reihenfolge:
   *   1. Text setzen, Blase unsichtbar einblenden zum Messen (kein Aufblitz).
   *   2. Abmessungen von Blase und Element per getBoundingClientRect() lesen.
   *   3. Vertikal: oberhalb wenn moeglich, sonst unterhalb (.tt-unten).
   *   4. Horizontal: auf Element-Mitte zentriert, dann Randabstand erzwingen.
   *   5. Pfeil auf Element-Mitte ausrichten (--tt-pfeil-links).
   *   6. Endposition setzen und sichtbar machen.
   */
  function _zeigen(el) {
    /* Tooltips global deaktiviert: nichts anzeigen. */
    if (document.body.classList.contains(TT_CLASS)) { return; }

    var text = el.getAttribute('data-tooltip');
    if (!text || !_blase) { return; }

    /* Text setzen, Klassen zuruecksetzen, zum Messen unsichtbar einblenden. */
    _blase.textContent = text;
    _blase.classList.remove('tt-unten');
    _blase.style.visibility = 'hidden';
    _blase.style.display     = 'block';
    _blase.style.left        = '0px';
    _blase.style.top         = '0px';

    /* Abmessungen ermitteln — erfordert einmaliges Reflow, kein sichtbarer Aufblitz. */
    var bBreite = _blase.offsetWidth;
    var bHoehe  = _blase.offsetHeight;
    var rect    = el.getBoundingClientRect();
    var vp      = window.innerWidth;

    /* ── Vertikale Positionierung ── */
    var oben;
    if (rect.top - bHoehe - PFEIL_ABSTAND < RAND) {
      /* Zu wenig Platz oben: Tooltip unterhalb des Elements anzeigen. */
      oben = rect.bottom + PFEIL_ABSTAND;
      _blase.classList.add('tt-unten');
    } else {
      /* Normalfall: Tooltip oberhalb des Elements. */
      oben = rect.top - bHoehe - PFEIL_ABSTAND;
    }

    /* ── Horizontale Positionierung ── */
    /* Idealzentrum: Mitte des Ausloeseelements. Dann Randabstand erzwingen. */
    var idealLinks = rect.left + rect.width / 2 - bBreite / 2;
    var links = Math.max(RAND, Math.min(idealLinks, vp - bBreite - RAND));

    /* ── Pfeil-Ausrichtung ── */
    /* Der Pfeil soll immer auf die Mitte des Elements zeigen, auch wenn
       die Blase horizontal verschoben wurde. */
    var pfeilLinks = (rect.left + rect.width / 2) - links;
    pfeilLinks = Math.max(10, Math.min(bBreite - 10, pfeilLinks));
    _blase.style.setProperty('--tt-pfeil-links', pfeilLinks + 'px');

    /* ── Endposition setzen und einblenden ── */
    _blase.style.top        = Math.round(oben)  + 'px';
    _blase.style.left       = Math.round(links) + 'px';
    _blase.style.visibility = 'visible';
  }

  /* ── Event-Delegation ─────────────────────────────────────────────────── */

  /**
   * Startet Event-Delegation auf document-Ebene (Capture-Phase).
   * Capture-Phase wird benoetigt damit auch Kinder von .tt-wrap und
   * andere Elemente ohne eigenes Bubble-Verhalten erfasst werden.
   */
  function _eventsStarten() {
    document.addEventListener('mouseenter', function (e) {
      var el = e.target && e.target.closest('[data-tooltip]');
      if (el) { _zeigen(el); }
    }, true);

    document.addEventListener('mouseleave', function (e) {
      var el = e.target && e.target.closest('[data-tooltip]');
      if (el) { _verbergen(); }
    }, true);

    /* Tooltip sofort ausblenden wenn die Seite gescrollt wird,
       da fixed-Elemente bei Scroll nicht automatisch nachziehen. */
    window.addEventListener('scroll', _verbergen, true);
  }

  /* ── Initialisierung ──────────────────────────────────────────────────── */

  /* Initialen Zustand so frueh wie moeglich setzen (verhindert Aufblitz). */
  _anwenden(_istSichtbar());

  /* DOM-Blase erstellen, Button verdrahten und Events starten. */
  function _init() {
    _blase = _blasenErstellen();

    var btn = document.getElementById(BTN_ID);
    if (btn) {
      btn.addEventListener('click', _umschalten);
      /* Button-Label nochmal setzen, da DOM jetzt sicher vorhanden. */
      _anwenden(_istSichtbar());
    }

    _eventsStarten();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _init);
  } else {
    _init();
  }
})();
