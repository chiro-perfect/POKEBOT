# bot.py - PokéDeck Version Finale (Slash & Prefixe)
import discord
from discord.ext import commands
from discord.ui import Button, View, Select
import asyncio
import aiohttp
import random
import io
import json
import os
import time
from PIL import Image, ImageFilter
from dotenv import load_dotenv

# --- SETUP ET CONSTANTES ---
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
print("TOKEN chargé ?", bool(TOKEN))

POKEAPI_BASE_URL = "https://pokeapi.co/api/v2"
DATA_FILE = "user_decks.json"

RARITIES = {
    "Mythique": {"chance": 0.01, "min_bst": 680, "color": 0xFFFFFF, "rank": 5, "emoji": "⚪", "reward": 5000},
    "Légendaire": {"chance": 0.04, "min_bst": 600, "color": 0x9B59B6, "rank": 4, "emoji": "🟣", "reward": 2500},
    "Épique": {"chance": 0.10, "min_bst": 500, "color": 0xE74C3C, "rank": 3, "emoji": "🔴", "reward": 1000},
    "Rare": {"chance": 0.35, "min_bst": 400, "color": 0xF1C40F, "rank": 2, "emoji": "🟡", "reward": 500},
    "Commun": {"chance": 0.50, "min_bst": 0, "color": 0x8B4513, "rank": 1, "emoji": "🟤", "reward": 100},
    "Chrome": {"chance": 0.001, "min_bst": 0, "color": 0xFFD700, "rank": 6, "emoji": "🌟", "reward": 10000},
}

ECONOMY = {
    "DUEL_WIN_REWARD": 5000,
    "EVOLVE_COST": 3000,
    "EVOLVE_REWARD": 5000,
    "BOOSTER_COST": 4000,
    "GUESS_REWARD": 1500,
}

ROMAN_NUMERALS = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII", 9: "IX"}

TYPE_MAP_FR = {
    "normal": "Normal", "fighting": "Combat", "flying": "Vol", "poison": "Poison", 
    "ground": "Sol", "rock": "Roche", "bug": "Insecte", "ghost": "Spectre", 
    "steel": "Acier", "fire": "Feu", "water": "Eau", "grass": "Plante", 
    "electric": "Électrik", "psychic": "Psy", "ice": "Glace", "dragon": "Dragon", 
    "dark": "Ténèbres", "fairy": "Fée", "unknown": "Inconnu", "shadow": "Ombre"
}

ENERGY_TYPES = {
    "Normal": {"emoji": "⚪", "color": 0xAAAAAA, "style": discord.ButtonStyle.secondary},
    "Feu": {"emoji": "🔥", "color": 0xFF4500, "style": discord.ButtonStyle.danger},
    "Eau": {"emoji": "💧", "color": 0x1E90FF, "style": discord.ButtonStyle.primary},
    "Plante": {"emoji": "🌿", "color": 0x3CB371, "style": discord.ButtonStyle.success},
    "Psy": {"emoji": "🔮", "color": 0x9400D3, "style": discord.ButtonStyle.blurple},
    "Combat": {"emoji": "👊", "color": 0xA0522D, "style": discord.ButtonStyle.secondary},
}
ENERGY_DECK = list(ENERGY_TYPES.keys()) * 2 

BIGDECK_COOLDOWN = 24 * 60 * 60
EVOLUTION_COOLDOWN = 24 * 60 * 60
BIGDECK_REROLLS = 5
MAX_HINTS = 5

# --- INITIALISATION BOT ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
# Suppression de 'tree = discord.app_commands.CommandTree(bot)' pour utiliser bot.tree par défaut.

user_decks = {}
all_pokemon_list = []
bigdeck_sessions = {}
rps_challenges = {}
active_deck_duels = {}
current_guess_game = None
tu_prefere_games = {}

# ---------------- PERSISTENCE & HELPERS ----------------

def load_user_decks():
    global user_decks
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            user_decks = {}
            for k, v in raw.items():
                uid = int(k)
                if isinstance(v, dict):
                    v.setdefault("deck", [])
                    v.setdefault("collection", list(v["deck"])) 
                    v.setdefault("pokedollars", 0) 
                    v.setdefault("last_bigdeck", 0)
                    v.setdefault("best_card", None)
                    for c in v.get("deck", []) + v.get("collection", []):
                        c.setdefault("last_draw", 0); c.setdefault("is_shiny", False); c.setdefault("moves", []); c.setdefault("stats_dict", {})
                    user_decks[uid] = v
                else:
                    user_decks[uid] = {"deck": list(v), "collection": list(v), "pokedollars": 0, "last_bigdeck": 0, "best_card": None}
            print(f"✅ {len(user_decks)} decks chargés.")
        except Exception as e:
            print(f"❌ Erreur chargement: {e}")
            user_decks = {}
    else: user_decks = {}

def save_user_decks():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in user_decks.items()}, f, indent=4, ensure_ascii=False)
    except Exception as e: print(f"❌ Erreur sauvegarde: {e}")

def get_card_rarity_info(card):
    return RARITIES.get(card.get("rarity_level", "Commun"), RARITIES["Commun"])

def add_pokedollars(user_id, amount):
    ud = user_decks.setdefault(user_id, {"deck": [], "collection": [], "pokedollars": 0, "last_bigdeck": 0, "best_card": None})
    ud["pokedollars"] = ud.get("pokedollars", 0) + amount
    save_user_decks()

def update_best_card(user_id):
    ud = user_decks.setdefault(user_id, {"deck": [], "collection": [], "pokedollars": 0, "last_bigdeck": 0, "best_card": None})
    collection = ud.get("collection", [])
    if not collection: ud["best_card"] = None; return
    
    best = None
    for c in collection:
        if not best: best = c; continue
        r1 = RARITIES.get(c.get("rarity_level","Commun"), {}).get("rank", 0)
        r2 = RARITIES.get(best.get("rarity_level","Commun"), {}).get("rank", 0)
        if r1 > r2 or (r1 == r2 and c.get("bst",0) > best.get("bst",0)) or (r1==r2 and c.get("bst",0)==best.get("bst",0) and c.get("is_shiny",False) and not best.get("is_shiny",False)):
            best = c
    ud["best_card"] = best.copy() if best else None

def add_card_to_collection(user_id, card):
    ud = user_decks.setdefault(user_id, {"deck": [], "collection": [], "pokedollars": 0, "last_bigdeck": 0, "best_card": None})
    card = dict(card); card.setdefault("last_draw", time.time()); ud["collection"].append(card)
    
    added_to_deck = False
    if len(ud["deck"]) < 6: ud["deck"].append(card); added_to_deck = True

    rarity = card.get("rarity_level", "Commun")
    reward = RARITIES.get(rarity, {}).get("reward", 100)
    add_pokedollars(user_id, reward)

    update_best_card(user_id); save_user_decks()
    return reward, added_to_deck

def calculate_bst(stats): return sum(s.get("base_stat", 0) for s in stats)

async def fetch_pokemon_moves(pokemon_id):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{POKEAPI_BASE_URL}/pokemon/{pokemon_id}") as resp:
                if resp.status != 200: return []
                data = await resp.json()
            moves = []; candidates = data.get("moves", [])[:20]
            types = [t["type"]["name"].capitalize() for t in data.get("types", [])]; primary_type = types[0] if types else "Normal"
            energy_map = {"Feu": "Feu", "Eau": "Eau", "Plante": "Plante", "Combat": "Combat", "Psy": "Psy", "Vol": "Normal", "Sol": "Combat", "Roche": "Combat", "Acier": "Normal", "Électrik": "Normal", "Glace": "Eau", "Dragon": "Normal", "Ténèbres": "Psy", "Fée": "Fée", "Poison": "Normal", "Insecte": "Plante"} 
            primary_energy = energy_map.get(primary_type, "Normal")
            
            for m in random.sample(candidates, min(len(candidates), 8)):
                name_en = m["move"]["name"].replace("-", " ").capitalize()
                try:
                    async with aiohttp.ClientSession() as s2:
                        async with s2.get(m["move"]["url"]) as r:
                            if r.status == 200: name_fr = next((n["name"] for n in (await r.json()).get("names",[]) if n["language"]["name"]=="fr"), name_en)
                            else: name_fr = name_en
                except: name_fr = name_en
                        
                power = random.choice([30, 50, 70, 90]); cost = random.randint(1, 3); energy_cost = {primary_energy: cost}
                moves.append({"name": name_fr, "power": power, "cost": energy_cost})
            if not moves: moves = [{"name":"Charge","power":50, "cost": {"Normal": 1}}]
            return moves[:4]
    except Exception as e:
        return [{"name":"Charge","power":50, "cost": {"Normal": 1}}]

async def fetch_pokemon_details(pokemon_id, is_shiny=False):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{POKEAPI_BASE_URL}/pokemon/{pokemon_id}") as r1:
                if r1.status != 200: return None; pdata = await r1.json()
            async with aiohttp.ClientSession() as session2:
                async with session2.get(f"{POKEAPI_BASE_URL}/pokemon-species/{pokemon_id}") as r2:
                    sdata = await r2.json() if r2.status == 200 else {}
            
            bst = calculate_bst(pdata.get("stats", []))
            rarity_level = next((name for name, info in sorted(RARITIES.items(), key=lambda x: -x[1]["min_bst"]) if name != "Chrome" and bst >= info.get("min_bst", 0)), "Commun")
            image_url = pdata["sprites"].get("front_shiny") if is_shiny else pdata["sprites"].get("front_default")
            name_fr = next((n["name"] for n in sdata.get("names", []) if n["language"]["name"] == "fr"), pdata.get("name","").capitalize()).capitalize()
            types = ", ".join([TYPE_MAP_FR.get(t["type"]["name"], t["type"]["name"].capitalize()) for t in pdata.get("types", [])])
            moves = await fetch_pokemon_moves(pokemon_id)
            stats_text = "\n".join([f"- {s['stat']['name'].capitalize()}: {s['base_stat']}" for s in pdata.get("stats", [])])
            
            generation = 1
            if sdata.get("generation"):
                gen_name = sdata["generation"]["name"]
                try: generation = int(gen_name.split("-")[-1].replace("i","1").replace("v","5").replace("x","10"))
                except: generation = 1
            generation_roman = ROMAN_NUMERALS.get(generation, str(generation))
            
            stats_dict = {s['stat']['name'].lower(): s['base_stat'] for s in pdata.get("stats", [])}
            stats_dict.setdefault("hp", stats_dict.get("hp", 50)); stats_dict.setdefault("attack", stats_dict.get("attack", 10)); stats_dict.setdefault("defense", stats_dict.get("defense", 10))

            return {"id": pdata.get("id"), "name_en": pdata.get("name","").capitalize(), "name_fr": name_fr, "bst": bst, "rarity_level": "Chrome" if is_shiny else rarity_level, "image_url": image_url, "is_shiny": is_shiny, "types": types, "stats": stats_text, "stats_dict": stats_dict, "moves": moves, "evolution_chain_url": sdata.get("evolution_chain", {}).get("url"), "evolution_stage": 0, "evolution_limit": 2, "last_evolution": 0, "last_draw": 0, "generation": generation_roman}
    except Exception as e: return None

async def load_all_pokemon():
    global all_pokemon_list
    if all_pokemon_list: return
    print("⏳ Chargement des Pokémon...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{POKEAPI_BASE_URL}/pokemon?limit=1000") as resp:
                if resp.status != 200: return
                data = await resp.json()
            all_pokemon_list = [{"id": int(item["url"].split("/")[-2]), "name": item["name"], "bst": 0} for item in data.get("results", [])]
        print(f"✅ {len(all_pokemon_list)} Pokémon chargés.")
    except Exception as e: print(f"❌ Erreur: {e}")

def get_rarity_emoji(name): return RARITIES.get(name, {}).get("emoji", "❓")
def get_rarity_color(name): return RARITIES.get(name, {}).get("color", discord.Color.blue().value)
def get_button_style_for_rarity(rarity_name): return {"Mythique": discord.ButtonStyle.secondary, "Légendaire": discord.ButtonStyle.primary, "Épique": discord.ButtonStyle.danger, "Rare": discord.ButtonStyle.success, "Commun": discord.ButtonStyle.secondary, "Chrome": discord.ButtonStyle.success}.get(rarity_name, discord.ButtonStyle.secondary)
async def get_blurred_sprite_file(pokemon_id, is_shiny=False, blur_level=18):
    try:
        url = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{'shiny/' if is_shiny else ''}{pokemon_id}.png"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200: return None; data = await resp.read()
        img = Image.open(io.BytesIO(data)).convert("RGBA"); blurred = img.filter(ImageFilter.GaussianBlur(blur_level))
        buf = io.BytesIO(); blurred.save(buf, format="PNG"); buf.seek(0)
        return discord.File(fp=buf, filename="pokemon_inconnu.png")
    except Exception: return None

# ----------------- VUES (UI) -----------------

class CardSelectionView(View):
    def __init__(self, user_id, deck, num_cards_required=3, timeout=90.0):
        super().__init__(timeout=timeout); self.user_id = user_id; self.deck = deck[:6]; self.num_cards_required = num_cards_required; self.selected = []; self.confirmed = False
        for i, card in enumerate(self.deck):
            label = f"#{i+1} {card.get('name_fr','?')[:18]}"; emoji = get_rarity_emoji(card.get("rarity_level","Commun"))
            btn = Button(label=f"{emoji} {label}", style=discord.ButtonStyle.secondary, custom_id=f"cs_{i}", callback=self.make_cb(i)); self.add_item(btn)
        confirm_btn = Button(label=f"✅ Confirmer (0/{self.num_cards_required})", style=discord.ButtonStyle.success, custom_id="cs_confirm", disabled=True, callback=self.confirm_cb); self.add_item(confirm_btn)

    def make_cb(self, idx):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.user_id: await interaction.response.send_message("Ce n'est pas votre sélection.", ephemeral=True); return
            if idx in self.selected: self.selected.remove(idx)
            else:
                if len(self.selected) >= self.num_cards_required: await interaction.response.send_message(f"Max {self.num_cards_required} cartes.", ephemeral=True); return
                self.selected.append(idx)
            for item in self.children:
                if isinstance(item, Button) and item.custom_id.startswith("cs_") and item.custom_id != "cs_confirm":
                    i = int(item.custom_id.split("_")[1])
                    if i in self.selected: item.style = discord.ButtonStyle.primary; item.label = "✓ " + item.label.replace("✓ ", "")
                    else: item.style = discord.ButtonStyle.secondary; item.label = item.label.replace("✓ ", "")
            confirm_btn = next((x for x in self.children if getattr(x, "custom_id", "") == "cs_confirm"), None)
            if confirm_btn: confirm_btn.disabled = len(self.selected) != self.num_cards_required; confirm_btn.label = f"✅ Confirmer ({len(self.selected)}/{self.num_cards_required})"
            try: await interaction.response.edit_message(view=self)
            except: pass
        return cb

    async def confirm_cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: await interaction.response.send_message("Pas votre sélection.", ephemeral=True); return
        self.confirmed = True
        for item in self.children: item.disabled = True
        try: await interaction.response.edit_message(content=f"✅ Sélection OK ({self.num_cards_required} cartes).", view=self)
        except: pass
        self.stop()
        
class DeckEditView(View):
    def __init__(self, ctx, collection):
        super().__init__(timeout=180.0); self.ctx = ctx; self.user_id = ctx.author.id; self.collection = collection
        active_deck = user_decks.get(self.user_id, {}).get("deck", [])
        self.current_deck_indices = []
        for d_card in active_deck:
            for i, c_card in enumerate(self.collection):
                if (c_card.get("id") == d_card.get("id") and c_card.get("name_fr") == d_card.get("name_fr") and c_card.get("is_shiny", False) == d_card.get("is_shiny", False)):
                    self.current_deck_indices.append(i); break
        self.max_deck_size = 6; self.page = 0; self.cards_per_page = 12
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        start_index = self.page * self.cards_per_page; end_index = start_index + self.cards_per_page; cards_to_show = self.collection[start_index:end_index]
        for i, card in enumerate(cards_to_show):
            coll_idx = start_index + i; is_in_deck = coll_idx in self.current_deck_indices
            rarity = card.get("rarity_level", "Commun"); emoji = "✅" if is_in_deck else get_rarity_emoji(rarity)
            label = f"{card.get('name_fr', '?')[:12]} ({card.get('bst', '?')})"
            is_shiny_mark = "🌟" if card.get("is_shiny") else ""
            btn_style = discord.ButtonStyle.primary if is_in_deck else get_button_style_for_rarity(rarity)
            btn = Button(label=f"{label}{is_shiny_mark}", style=btn_style, custom_id=f"deck_edit_{coll_idx}", emoji=emoji, row=i // 4, callback=self.make_card_cb(coll_idx)); self.add_item(btn)

        self.add_item(Button(label="⬅️ Précédent", custom_id="page_prev", disabled=self.page == 0, row=4, callback=self.page_prev_cb))
        self.add_item(Button(label=f"💾 Sauver ({len(self.current_deck_indices)}/6)", custom_id="deck_save", style=discord.ButtonStyle.success, disabled=len(self.current_deck_indices) != self.max_deck_size, row=4, callback=self.deck_save_cb))
        self.add_item(Button(label="Suivant ➡️", custom_id="page_next", disabled=end_index >= len(self.collection), row=4, callback=self.page_next_cb))

    def make_card_cb(self, coll_idx):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.user_id: await interaction.response.send_message("Pas votre PC.", ephemeral=True); return
            if coll_idx in self.current_deck_indices: self.current_deck_indices.remove(coll_idx)
            else:
                if len(self.current_deck_indices) >= self.max_deck_size: await interaction.response.send_message(f"Le deck est plein (Max {self.max_deck_size}). Retirez-en un d'abord.", ephemeral=True); return
                self.current_deck_indices.append(coll_idx)
            self.update_buttons(); await interaction.response.edit_message(view=self)
        return cb

    async def page_prev_cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: await interaction.response.send_message("Pas votre PC.", ephemeral=True); return
        self.page = max(0, self.page - 1); self.update_buttons(); await interaction.response.edit_message(view=self)

    async def page_next_cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: await interaction.response.send_message("Pas votre PC.", ephemeral=True); return
        self.page += 1; self.update_buttons(); await interaction.response.edit_message(view=self)
        
    async def deck_save_cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: await interaction.response.send_message("Pas votre PC.", ephemeral=True); return
        if len(self.current_deck_indices) != self.max_deck_size: await interaction.response.send_message("Sélectionnez 6 cartes.", ephemeral=True); return
        ud = user_decks.get(self.user_id)
        if ud:
            ud["deck"] = [self.collection[i] for i in self.current_deck_indices]; update_best_card(self.user_id); save_user_decks()
            await interaction.response.edit_message(content="✅ Deck mis à jour ! Utilisez `/deck` pour l'afficher.", embed=None, view=None); self.stop()
        else: await interaction.response.send_message("Erreur de sauvegarde.", ephemeral=True)

class EnergyAttackSelectView(View):
    def __init__(self, manager, user_id, timeout=60.0):
        super().__init__(timeout=timeout); self.manager = manager; self.user_id = user_id
        active_card = manager.get_active_card(user_id); self.moves = active_card.get("moves", [])[:4] or [{"name":"Charge","power":50, "cost": {"Normal": 1}}]
        self.player_energy = manager.energy_stocks[user_id]
        
        for i, m in enumerate(self.moves):
            cost_str = "".join([f"{ENERGY_TYPES.get(t, {}).get('emoji', '❓')}{c}" for t, c in m["cost"].items()])
            label = f"{m['name']} ({cost_str})"
            can_afford = all(self.player_energy.get(t, 0) >= c for t, c in m["cost"].items())
            dominant_energy = next(iter(m["cost"].keys()), "Normal")
            btn_style = ENERGY_TYPES.get(dominant_energy, ENERGY_TYPES["Normal"])["style"]
            btn = Button(label=label, style=btn_style, custom_id=f"atk_{user_id}_{i}", disabled=not can_afford, row=i//2, callback=self.make_cb(i)); self.add_item(btn)
        
        pass_btn = Button(label="🔄 Piocher / Passer (Gratuit)", style=discord.ButtonStyle.secondary, custom_id=f"pass_{user_id}", row=3, callback=self.pass_cb); self.add_item(pass_btn)

    def make_cb(self, idx):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.user_id: await interaction.response.send_message("Pas votre tour.", ephemeral=True); return
            for item in self.children: item.disabled = True
            try: await interaction.response.edit_message(view=self)
            except: pass
            await self.manager.handle_move(self.user_id, idx); self.stop()
        return cb
    
    async def pass_cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: await interaction.response.send_message("Pas votre tour.", ephemeral=True); return
        for item in self.children: item.disabled = True
        try: await interaction.response.edit_message(view=self)
            except: pass
        await self.manager.handle_move(self.user_id, -1, is_pass=True); self.stop()

    async def on_timeout(self): await self.manager.handle_timeout(self.user_id)

class StealSelectView(View):
    def __init__(self, ctx, info):
        super().__init__(timeout=60.0); self.ctx = ctx; self.info = info; loser_cards = info.get("loser_cards_ko", [])
        for i, c in enumerate(loser_cards):
            emoji = get_rarity_emoji(c.get("rarity_level","Commun")); label = f"{c.get('name_fr','?')[:20]}"
            btn_style = get_button_style_for_rarity(c.get("rarity_level", "Commun"))
            btn = Button(label=f"{emoji} {label}", style=btn_style, custom_id=f"steal_{i}", callback=self.make_cb(i)); self.add_item(btn)

    def make_cb(self, idx):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.info.get("winner_id"): await interaction.response.send_message("Seul le gagnant peut voler.", ephemeral=True); return
            stolen = self.info["loser_cards_ko"][idx]; loser_deck_ud = user_decks.get(self.info["loser_id"], {})
            
            def remove_from_list(card_list, target_card):
                for i, c in enumerate(list(card_list)):
                    if (c.get("id") == target_card.get("id") and c.get("name_fr") == target_card.get("name_fr") and c.get("is_shiny", False) == target_card.get("is_shiny", False)):
                        card_list.pop(i); return True
                return False
                
            remove_from_list(loser_deck_ud.get("deck", []), stolen); remove_from_list(loser_deck_ud.get("collection", []), stolen)
            add_card_to_collection(self.info["winner_id"], stolen)
            update_best_card(self.info["loser_id"]); save_user_decks()
            
            emoji = get_rarity_emoji(stolen.get("rarity_level", "Commun"))
            await interaction.response.edit_message(content=f"✅ {interaction.user.mention} a volé **{stolen['name_fr']}** {emoji} ({stolen.get('rarity_level','')}) ! Cette carte est maintenant dans sa collection/PC.", embed=None, view=None)
            try: del active_deck_duels[self.ctx.channel.id]
            except KeyError: pass
            self.stop() 
        return cb

    async def on_timeout(self):
        try: await self.ctx.send("⏳ Temps écoulé pour le vol. Le duel est terminé sans vol.");
        except: pass

class BigDeckView(View):
    def __init__(self, user_id, session):
        super().__init__(timeout=120.0); self.user_id = user_id; self.session = session
        reroll_btn = Button(label=f"🔄 Reroll ({session['attempts']})", style=discord.ButtonStyle.secondary, callback=self.reroll_cb)
        keep_btn = Button(label="✅ Garder", style=discord.ButtonStyle.success, callback=self.keep_cb)
        cancel_btn = Button(label="❌ Annuler", style=discord.ButtonStyle.danger, callback=self.cancel_cb)
        self.add_item(reroll_btn); self.add_item(keep_btn); self.add_item(cancel_btn)

    async def reroll_cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: await interaction.response.send_message("Pas votre session.", ephemeral=True); return
        if self.session["attempts"] <= 0: await interaction.response.send_message("Plus de rerolls.", ephemeral=True); return
        candidate = random.choice(all_pokemon_list); card = await fetch_pokemon_details(candidate["id"], is_shiny=(random.random() < RARITIES["Chrome"]["chance"]))
        if not card: await interaction.response.send_message("Erreur tirage.", ephemeral=True); return
        self.session["current_card"] = card; self.session["attempts"] -= 1
        file = await get_blurred_sprite_file(card["id"], is_shiny=card.get("is_shiny",False), blur_level=10)
        rarity_emoji = get_rarity_emoji(card.get("rarity_level","Commun"))
        embed = discord.Embed(title="✨ BigDeck (reroll) ✨", description=f"Rareté: {rarity_emoji} {card.get('rarity_level','?')} - BST: {card.get('bst','?')}\nRerolls: {self.session['attempts']}", color=get_rarity_color(card.get("rarity_level","Commun")))
        embed.set_image(url="attachment://pokemon_inconnu.png")
        try: await interaction.response.edit_message(embed=embed, attachments=[file] if file else [], view=self)
        except: await interaction.response.send_message(embed=embed, file=file, view=self)

    async def keep_cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: await interaction.response.send_message("Pas votre session.", ephemeral=True); return
        final_card = self.session.get("current_card")
        if not final_card: await interaction.response.send_message("Aucune carte.", ephemeral=True); return
        reward, added_to_deck = add_card_to_collection(self.user_id, final_card)
        msg = f"🎉 **{final_card['name_fr']}** ({final_card.get('rarity_level','')}) obtenu ! **+ ₽{reward}**."
        if not added_to_deck: msg += f"\n(Ajouté à votre PC. Deck actif plein.)"
        try: await interaction.response.edit_message(content=msg, embed=None, view=None, attachments=[]); bigdeck_sessions.pop(self.user_id, None); self.stop()
        except: await interaction.response.send_message(msg)

    async def cancel_cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: await interaction.response.send_message("Pas votre session.", ephemeral=True); return
        try: await interaction.response.edit_message(content="Tirage annulé.", embed=None, view=None, attachments=[]); bigdeck_sessions.pop(self.user_id, None); self.stop()
        except: await interaction.response.send_message("Annulé.")
        
    async def on_timeout(self): bigdeck_sessions.pop(self.user_id, None)

class TuPrefereView(View):
    def __init__(self, ctx, card1, card2):
        super().__init__(timeout=90.0); self.ctx = ctx; self.user_id = ctx.author.id; self.cards = [card1, card2]; self.current_selection = 0
        self.update_buttons()

    def update_buttons(self):
        self.clear_items(); c1, c2 = self.cards
        btn1_style = discord.ButtonStyle.primary if self.current_selection == 0 else discord.ButtonStyle.secondary
        btn2_style = discord.ButtonStyle.primary if self.current_selection == 1 else discord.ButtonStyle.secondary
        btn1 = Button(label=f"Choisir {c1['name_fr']}", style=btn1_style, custom_id="tp_0", callback=self.make_cb(0))
        btn2 = Button(label=f"Choisir {c2['name_fr']}", style=btn2_style, custom_id="tp_1", callback=self.make_cb(1))
        self.add_item(btn1); self.add_item(btn2)
        card_to_change = self.cards[1-self.current_selection]
        change_btn = Button(label=f"🔄 Changer {card_to_change['name_fr']}", style=discord.ButtonStyle.secondary, row=1, callback=self.change_cb)
        finish_btn = Button(label="✅ J'ai choisi !", style=discord.ButtonStyle.success, row=1, callback=self.finish_cb)
        self.add_item(change_btn); self.add_item(finish_btn)

    def make_cb(self, index):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.user_id: await interaction.response.send_message("Pas votre jeu.", ephemeral=True); return
            self.current_selection = index; self.update_buttons(); embed = self.create_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        return cb
        
    async def change_cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: await interaction.response.send_message("Pas votre jeu.", ephemeral=True); return
        await interaction.response.defer()
        card_to_keep = self.cards[self.current_selection]; new_card = await self.draw_new_card(card_to_keep); self.cards[1-self.current_selection] = new_card
        self.update_buttons(); embed = self.create_embed()
        await interaction.edit_original_response(embed=embed, view=self)

    async def finish_cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id: await interaction.response.send_message("Pas votre jeu.", ephemeral=True); return
        chosen_card = self.cards[self.current_selection]; reward, added_to_deck = add_card_to_collection(self.user_id, chosen_card)
        msg = f"🎉 **{interaction.user.mention}** a choisi **{chosen_card['name_fr']}** ! Carte ajoutée à votre collection. **+ ₽{reward}**."
        if not added_to_deck: msg += f"\n(Deck actif plein.)"
        await interaction.response.edit_message(content=msg, embed=None, view=None, attachments=[]); tu_prefere_games.pop(self.ctx.channel.id, None); self.stop()

    async def draw_new_card(self, current_card):
        while True:
            pick = random.choice(all_pokemon_list)
            if pick["id"] != current_card["id"]:
                card = await fetch_pokemon_details(pick["id"], is_shiny=False)
                if card: return card
    
    def create_embed(self):
        c1, c2 = self.cards; chosen = self.cards[self.current_selection]; opponent = self.cards[1-self.current_selection]
        embed = discord.Embed(title="❓ Tu Préfères... ?", description=f"**{c1['name_fr']}** ({c1.get('bst', '?')}) vs **{c2['name_fr']}** ({c2.get('bst', '?')})", color=discord.Color.blurple())
        embed.add_field(name="Sélection Actuelle:", value=f"✅ **{chosen['name_fr']}**", inline=False)
        embed.set_image(url=chosen["image_url"]); embed.set_thumbnail(url=opponent["image_url"])
        return embed

    async def on_timeout(self): tu_prefere_games.pop(self.ctx.channel.id, None);

# ---------------- DECK DUEL MANAGER (ÉNERGIE) ----------------

class DeckDuelManager:
    def __init__(self, ctx, challenger_id, opponent_id, challenger_cards, opponent_cards):
        self.ctx = ctx; self.channel = ctx.channel; self.guild = ctx.guild; self.challenger_id = challenger_id; self.opponent_id = opponent_id
        self.challenger_cards = [dict(c) for c in challenger_cards]; self.opponent_cards = [dict(c) for c in opponent_cards]
        for c in self.challenger_cards + self.opponent_cards:
            stats_dict = c.get("stats_dict", {}); c.setdefault("current_hp", stats_dict.get("hp", c.get("bst", 100))); c.setdefault("stats_dict", stats_dict); c["stats_dict"].setdefault("hp", c.get("current_hp"))

        self.challenger_index = 0; self.opponent_index = 0
        sc = self.challenger_cards[0].get("stats_dict", {}).get("speed", 0); so = self.opponent_cards[0].get("stats_dict", {}).get("speed", 0)
        self.active_player_id = self.challenger_id if sc >= so else self.opponent_id
        self.turn = 1; self.last_message = None; self.status = "FIGHT"
        self.energy_stocks = {self.challenger_id: {t: 0 for t in ENERGY_TYPES}, self.opponent_id: {t: 0 for t in ENERGY_TYPES}}
        self.energy_deck = list(ENERGY_DECK); random.shuffle(self.energy_deck); self.draw_energy(self.active_player_id)

    def draw_energy(self, user_id):
        if not self.energy_deck: self.energy_deck = list(ENERGY_DECK); random.shuffle(self.energy_deck)
        drawn_card = self.energy_deck.pop(); self.energy_stocks[user_id][drawn_card] = self.energy_stocks[user_id].get(drawn_card, 0) + 1; return drawn_card

    def get_active_card(self, user_id):
        if user_id == self.challenger_id: return self.challenger_cards[self.challenger_index] if self.challenger_index < len(self.challenger_cards) else None
        else: return self.opponent_cards[self.opponent_index] if self.opponent_index < len(self.opponent_cards) else None

    def get_opponent_card(self, user_id):
        if user_id == self.challenger_id: return self.opponent_cards[self.opponent_index] if self.opponent_index < len(self.opponent_cards) else None
        else: return self.challenger_cards[self.challenger_index] if self.challenger_index < len(self.challenger_cards) else None

    async def handle_timeout(self, user_id):
        if self.status != "FIGHT": return
        loser = user_id; winner = self.opponent_id if loser == self.challenger_id else self.challenger_id
        await self.end_duel(winner, f"⏱️ <@{loser}> n'a pas joué à temps, l'adversaire gagne par forfait.")

    async def handle_move(self, user_id, move_index, is_pass: bool = False):
        if self.status != "FIGHT": return
        attacker = self.get_active_card(user_id); defender = self.get_opponent_card(user_id)
        drawn_energy = self.draw_energy(user_id)
        text = f"**{self.get_player_name(user_id)}** pioche une Énergie {ENERGY_TYPES[drawn_energy]['emoji']} **{drawn_energy}**."

        if is_pass:
            text += f"\n<@{user_id}> passe son tour pour accumuler de l'énergie."
        else:
            if not attacker or not defender: return
            moves = attacker.get("moves", []) or [{"name":"Charge","power":50, "cost": {"Normal": 1}}]
            move = moves[move_index]
            energy_consumption_str = " (consomme "
            for energy_type, cost in move["cost"].items():
                self.energy_stocks[user_id][energy_type] -= cost; energy_consumption_str += f"{ENERGY_TYPES[energy_type]['emoji']}{cost} "
            energy_consumption_str += ")"
            
            atk = attacker.get("stats_dict", {}).get("attack", 10); df = defender.get("stats_dict", {}).get("defense", 10); base = move.get("power", 50)
            damage = int((base * atk / max(1, df)) * random.uniform(0.9,1.1) / 10); damage = max(1, damage); defender["current_hp"] -= damage

            text += f"{energy_consumption_str}\n**{self.get_player_name(user_id)}** → **{attacker['name_fr']}** utilise **{move['name']}** ! **{defender['name_fr']}** subit **-{damage} PV** ({max(0,defender['current_hp'])}/{defender['stats_dict'].get('hp','?')} PV)."

            if defender["current_hp"] <= 0:
                text += f"\n💥 **{defender['name_fr']}** est KO !"
                if user_id == self.challenger_id: self.opponent_index += 1
                else: self.challenger_index += 1
                
                if self.challenger_index >= len(self.challenger_cards) or self.opponent_index >= len(self.opponent_cards): await self.end_duel(user_id, text); return
                    
                new_def = self.get_opponent_card(user_id); text += f"\n➡️ **{new_def['name_fr']}** entre !"
                new_att = self.get_active_card(user_id)
                if new_att and new_def and new_att.get("stats_dict", {}).get("speed",0) < new_def.get("stats_dict", {}).get("speed",0):
                    self.active_player_id = self.opponent_id if user_id == self.challenger_id else self.challenger_id
            
        self.active_player_id = self.opponent_id if user_id == self.challenger_id else self.challenger_id; self.turn += 1
        await self.send_battle_update(text)

    def format_energy_stock(self, user_id):
        stock = self.energy_stocks.get(user_id, {}); parts = []
        for type_name, info in ENERGY_TYPES.items():
            count = stock.get(type_name, 0); 
            if count > 0: parts.append(f"{info['emoji']}{count}")
        return " ".join(parts) if parts else "(Vide)"

    async def send_battle_update(self, action_message=None):
        c_user = self.guild.get_member(self.challenger_id); o_user = self.guild.get_member(self.opponent_id)
        card_c = self.challenger_cards[self.challenger_index] if self.challenger_index < len(self.challenger_cards) else {"name_fr":"(KO)","image_url":None,"rarity_level":"", "stats_dict":{"hp":0},"current_hp":0}
        card_o = self.opponent_cards[self.opponent_index] if self.opponent_index < len(self.opponent_cards) else {"name_fr":"(KO)","image_url":None,"rarity_level":"", "stats_dict":{"hp":0},"current_hp":0}

        active = self.active_player_id; c_energy = self.format_energy_stock(self.challenger_id); o_energy = self.format_energy_stock(self.opponent_id)
        
        embed = discord.Embed(title=f"⚔️ DECK DUEL — {c_user.display_name} vs {o_user.display_name} (Tour {self.turn})",
                              description=action_message or f"C'est à <@{active}>.", color=discord.Color.red())
        
        embed.add_field(name=f"Stock de {c_user.display_name}", value=c_energy, inline=True); embed.add_field(name="\u200b", value="\u200b", inline=True); embed.add_field(name=f"Stock de {o_user.display_name}", value=o_energy, inline=True)
        embed.add_field(name=f"Mon Pokémon : {card_c['name_fr']}", value=f"PV: {max(0,card_c.get('current_hp',0))}/{card_c.get('stats_dict',{}).get('hp','?')}", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True); embed.add_field(name=f"Adversaire : {card_o['name_fr']}", value=f"PV: {max(0,card_o.get('current_hp',0))}/{card_o.get('stats_dict',{}).get('hp','?')}", inline=True)

        if card_c.get("image_url"): embed.set_thumbnail(url=card_c.get("image_url"))
        if card_o.get("image_url"): embed.set_image(url=card_o.get("image_url"))

        view = EnergyAttackSelectView(self, active, timeout=60.0)

        if self.last_message:
            try: await self.last_message.delete()
            except: pass
        self.last_message = await self.channel.send(content=f"⚡ <@{active}> — **Tour {self.turn}**. Choisissez une action :", embed=embed, view=view)

    async def end_duel(self, winner_id, final_message):
        self.status = "ENDED"
        loser = self.opponent_id if winner_id == self.challenger_id else self.challenger_id
        if loser == self.challenger_id: ko_cards = self.challenger_cards[self.challenger_index:]
        else: ko_cards = self.opponent_cards[self.opponent_index:]

        reward = ECONOMY["DUEL_WIN_REWARD"]; add_pokedollars(winner_id, reward)
        
        embed = discord.Embed(title=f"👑 VICTOIRE : {self.get_player_name(winner_id)} gagne !",
                              description=f"{final_message}\n\n**+ ₽{reward} Pokédollars !**\n\n**Le gagnant peut voler une carte KO en cliquant sur un bouton ci-dessous.**",
                              color=discord.Color.gold())
        if self.last_message:
            try: await self.last_message.delete()
            except: pass
        
        view = StealSelectView(self.ctx, {"manager": self, "winner_id": winner_id, "loser_id": loser, "loser_cards_ko": ko_cards})
        self.last_message = await self.channel.send(embed=embed, view=view)
        active_deck_duels[self.channel.id] = {"manager": self, "winner_id": winner_id, "loser_id": loser, "loser_cards_ko": ko_cards}

# ---------------- COMMANDES SLASH & PREFIX ----------------

@bot.event
async def on_ready():
    print("✅ Bot prêt:", bot.user)
    load_user_decks()
    bot.loop.create_task(load_all_pokemon())
    
    # Correction de l'erreur: Synchronisation via bot.tree
    await bot.tree.sync()
    print("✅ Commandes Slash synchronisées.")

@bot.command(name="help", aliases=["aide","pokehelp"])
async def pokehelp(ctx):
    await send_help_embed(ctx)

@bot.tree.command(name="help", description="Affiche la liste des commandes et l'aide.")
async def slash_help(interaction: discord.Interaction):
    await send_help_embed(interaction)

async def send_help_embed(target):
    embed = discord.Embed(title="🤖 PokéBot — Aide (Slash & Prefix)", description="Toutes les commandes fonctionnent avec `/` ou `!`", color=discord.Color.blue())
    embed.add_field(name="💼 Collection & Économie (₽)", value="`/carte` ou `!carte` — Tire une carte (gain ₽)\n`/booster` ou `!booster` — Pioche 5 cartes (coût ₽)\n`/deck` ou `!deck` — Affiche ton deck actif / **Modifier** (PC)\n`/solde` ou `!solde` — Affiche tes Pokédollars (₽)", inline=False)
    embed.add_field(name="⚔️ Évolution & Duels", value="`/evolve [slot]` — Défi **Eau/Feu/Plante** pour évolution (coût/gain ₽)\n`/pfc [choix]` — Joue au défi évolution\n`/deckduel @user` — Duel stratégique (**Système d'Énergie**, gain ₽)", inline=False)
    embed.add_field(name="🎲 Mini-jeux", value="`/devine` — Quel est ce Pokémon ?\n`/indice` — Défloutage progressif\n`/tuprefere` — Choisis entre deux Pokémon", inline=False)
    
    if isinstance(target, commands.Context): await target.send(embed=embed)
    else: await target.response.send_message(embed=embed, ephemeral=False)

# --- Commandes de Collection et Économie ---

@bot.command()
async def carte(ctx): await cmd_carte(ctx.author, ctx)
@bot.tree.command(name="carte", description="Tire une carte Pokémon aléatoire.")
async def slash_carte(interaction: discord.Interaction): await cmd_carte(interaction.user, interaction)

async def cmd_carte(user, target):
    if not all_pokemon_list: await target.response.send_message("Données en cours de chargement...") if isinstance(target, discord.Interaction) else target.send("Données en cours de chargement..."); return
    is_shiny = random.random() < RARITIES["Chrome"]["chance"]; pid = random.choice(all_pokemon_list)["id"]; card = await fetch_pokemon_details(pid, is_shiny=is_shiny)
    if not card: return
    reward, added_to_deck = add_card_to_collection(user.id, card)
    emoji = get_rarity_emoji(card.get("rarity_level","Commun")); embed = discord.Embed(title=f"🎴 {card['name_fr']} !", color=get_rarity_color(card.get("rarity_level","Commun")))
    embed.set_thumbnail(url=card.get("image_url")); embed.add_field(name="Rareté", value=f"{emoji} {card.get('rarity_level')}", inline=True)
    embed.add_field(name="BST", value=str(card.get("bst","?")), inline=True); embed.add_field(name="Gain", value=f"**+ ₽{reward}**", inline=True)
    msg = f"**{card['name_fr']}** tiré. "; 
    if not added_to_deck: msg += f"\n(Ajouté à votre **PC/Collection**. Deck actif plein.)"
    if isinstance(target, discord.Interaction): await target.response.send_message(msg, embed=embed)
    else: await target.send(msg, embed=embed)

@bot.command()
async def booster(ctx): await cmd_booster(ctx.author, ctx)
@bot.tree.command(name="booster", description="Pioche 5 cartes Pokémon (coût ₽).")
async def slash_booster(interaction: discord.Interaction): await cmd_booster(interaction.user, interaction)

async def cmd_booster(user, target):
    uid = user.id; ud = user_decks.get(uid, {}); cost = ECONOMY["BOOSTER_COST"]
    if ud.get("pokedollars", 0) < cost: 
        msg = f"❌ Vous n'avez pas assez de Pokédollars. Coût: **₽{cost}**."
        if isinstance(target, discord.Interaction): await target.response.send_message(msg, ephemeral=True)
        else: await target.send(msg)
        return
    if not all_pokemon_list: return
    
    if isinstance(target, discord.Interaction): await target.response.defer()

    add_pokedollars(uid, -cost); pulled_cards = []; total_reward = 0
    for _ in range(5):
        is_shiny = random.random() < RARITIES["Chrome"]["chance"]; pid = random.choice(all_pokemon_list)["id"]; card = await fetch_pokemon_details(pid, is_shiny=is_shiny)
        if card: reward, _ = add_card_to_collection(uid, card); total_reward += reward; pulled_cards.append(card)
            
    current_dollars = user_decks.get(uid, {}).get("pokedollars", 0)
    embed = discord.Embed(title="✨ Booster de Cartes (5) ✨", description=f"Ouverture pour **₽{cost}**. Solde restant : **₽{current_dollars}**.", color=discord.Color.gold())
    list_cards = [];
    for c in pulled_cards:
        rarity_info = get_card_rarity_info(c); emoji = rarity_info.get("emoji","")
        list_cards.append(f"{emoji} **{c['name_fr']}** ({c['rarity_level']}) - BST: {c.get('bst', '?')}")
        
    embed.add_field(name="Cartes Obtenues (Ajoutées au PC)", value="\n".join(list_cards), inline=False)
    if isinstance(target, discord.Interaction): await target.followup.send(embed=embed)
    else: await target.send(embed=embed)


@bot.command()
async def solde(ctx): await cmd_solde(ctx.author, ctx)
@bot.tree.command(name="solde", description="Affiche votre solde de Pokédollars (₽).")
async def slash_solde(interaction: discord.Interaction): await cmd_solde(interaction.user, interaction)

async def cmd_solde(user, target):
    dollars = user_decks.get(user.id, {}).get("pokedollars", 0)
    embed = discord.Embed(title="💰 Pokédollar (₽) Solde", description=f"{user.mention}, votre solde est de **₽{dollars}**.", color=discord.Color.green())
    embed.set_thumbnail(url="https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items/poke-dollar.png")
    if isinstance(target, discord.Interaction): await target.response.send_message(embed=embed)
    else: await target.send(embed=embed)

@bot.command()
async def bigdeck(ctx): await cmd_bigdeck(ctx.author, ctx)
@bot.tree.command(name="bigdeck", description="Tirage quotidien avec rerolls.")
async def slash_bigdeck(interaction: discord.Interaction): await cmd_bigdeck(interaction.user, interaction)

async def cmd_bigdeck(user, target):
    uid = user.id; ud = user_decks.setdefault(uid, {"deck":[], "collection":[], "pokedollars": 0, "last_bigdeck":0, "best_card":None}); now = time.time()
    if now - ud.get("last_bigdeck",0) < BIGDECK_COOLDOWN:
        rem = BIGDECK_COOLDOWN - (now - ud["last_bigdeck"]); h = int(rem//3600); m = int((rem%3600)//60)
        msg = f"⏳ Recharge dans {h}h{m}m."
        if isinstance(target, discord.Interaction): await target.response.send_message(msg, ephemeral=True)
        else: await target.send(msg)
        return
    if not all_pokemon_list: return
    
    if isinstance(target, discord.Interaction): await target.response.defer()
    
    candidate = random.choice(all_pokemon_list); card = await fetch_pokemon_details(candidate["id"], is_shiny=(random.random() < RARITIES["Chrome"]["chance"]))
    if not card: return
    session = {"current_card": card, "attempts": BIGDECK_REROLLS, "start": now}; bigdeck_sessions[uid] = session
    file = await get_blurred_sprite_file(card["id"], is_shiny=card.get("is_shiny",False), blur_level=14)
    rarity_info = get_card_rarity_info(card)
    
    embed = discord.Embed(title="✨ BigDeck Quotidien ✨", description=f"BST: {card.get('bst','?')} — {rarity_info.get('emoji')} {rarity_info.get('rarity_level')}\nRerolls: {session['attempts']}", color=rarity_info.get("color"))
    embed.set_image(url="attachment://pokemon_inconnu.png")
    view = BigDeckView(uid, session); user_decks[uid]["last_bigdeck"] = now; save_user_decks()
    
    if isinstance(target, discord.Interaction):
        await target.followup.send(embed=embed, file=file, view=view)
    else:
        await target.send(embed=embed, file=file, view=view)

@bot.command()
async def deck(ctx, member: discord.Member = None): await cmd_deck(ctx.author, ctx, member)
@bot.tree.command(name="deck", description="Affiche votre deck actif et permet de le modifier (PC).")
async def slash_deck(interaction: discord.Interaction, member: discord.Member = None): await cmd_deck(interaction.user, interaction, member)

async def cmd_deck(user, target, member):
    member_id = member.id if member else user.id
    target_display = member.display_name if member else user.display_name
    
    ud = user_decks.get(member_id, {"deck":[], "collection":[]}); deck = ud.get("deck", [])
    
    view = View(timeout=30)
    async def pc_cb(interaction: discord.Interaction):
        if interaction.user.id != user.id: await interaction.response.send_message("Pas votre PC.", ephemeral=True); return
        pc_list = sorted(ud.get("collection", []), key=lambda c: (get_card_rarity_info(c).get("rank", 0), c.get("bst", 0)), reverse=True)
        embed_pc = discord.Embed(title=f"💻 PC/Collection de {target_display} ({len(pc_list)} cartes)", color=discord.Color.purple())
        rarity_groups = {}
        for c in pc_list:
            rarity = c.get("rarity_level", "Commun"); emoji = get_rarity_emoji(rarity); name = c.get('name_fr','?')
            bst = c.get('bst', '?'); is_shiny = "🌟" if c.get("is_shiny") else ""
            rarity_groups.setdefault(rarity, []).append(f"{emoji} {name} (BST: {bst}) {is_shiny}")
        for rarity, cards in rarity_groups.items():
            value = "\n".join(cards[:10]); 
            if len(cards) > 10: value += f"\n... et {len(cards)-10} autres."
            if not value: value = "(Vide)"
            embed_pc.add_field(name=f"[{rarity} ({len(rarity_groups[rarity])}x)]", value=value, inline=False)
        await interaction.response.send_message(embed=embed_pc, ephemeral=False); view.stop()

    if not deck and not ud.get("collection", []): 
        msg = f"{target_display} n'a pas de cartes."
        if isinstance(target, discord.Interaction): await target.response.send_message(msg); return
        else: await target.send(msg); return

    if not deck: 
        msg = f"{target_display} n'a pas de deck actif (0/6). Utilisez `/carte` ou **Modifier**."
        if member is None and ud.get("collection", []):
            if isinstance(target, discord.Interaction): await target.response.send_message(msg, view=view);
            else: await target.send(msg, view=view)
            return

    best_card = ud.get("best_card") or deck[0] if deck else {"name_fr": "", "rarity_level": "Commun", "bst": 0}
    embed = discord.Embed(title=f"🎒 Deck Actif de {target_display} ({len(deck)}/6)", color=get_rarity_color(best_card.get("rarity_level", "Commun")))
    embed.set_author(name=target_display, icon_url=user.display_avatar.url)
    if best_card.get("image_url"):
        embed.set_image(url=best_card["image_url"])
        rarity_info = get_card_rarity_info(best_card)
        embed.set_footer(text=f"⭐ Meilleur: {best_card['name_fr']} ({rarity_info.get('emoji','')} {rarity_info.get('rarity_level')}) (BST: {best_card['bst']})")

    for i in range(6):
        if i < len(deck):
            c = deck[i]; emoji = get_rarity_emoji(c.get("rarity_level","Commun")); is_shiny = "🌟" if c.get("is_shiny") else ""
            embed.add_field(name=f"#{i+1}: {c.get('name_fr')} {is_shiny}", value=f"{emoji} {c.get('rarity_level')} — BST: {c.get('bst')}", inline=True)
        else: embed.add_field(name=f"#{i+1}", value="(Vide)", inline=True)
            
    if member is None and len(ud.get("collection",[])) >= 6:
        async def edit_cb(interaction: discord.Interaction):
            if interaction.user.id != user.id: await interaction.response.send_message("Pas votre deck.", ephemeral=True); return
            view_edit = DeckEditView(target, ud["collection"])
            if isinstance(target, discord.Interaction): await interaction.response.send_message(f"**PC/Collection:** Sélectionnez 6 cartes pour votre deck actif (Actuel: {len(view_edit.current_deck_indices)}/6)", view=view_edit, ephemeral=True)
            else: await interaction.response.edit_message(content="**PC/Collection:** Sélectionnez 6 cartes pour votre deck actif :", embed=None, view=None); await target.send(f"Sélection actuelle: {len(view_edit.current_deck_indices)}/6", view=view_edit)
            view.stop()
            
        edit_btn = Button(label="🔄 Modifier le deck (PC)", style=discord.ButtonStyle.primary); pc_btn = Button(label="💻 Voir PC (Collection)", style=discord.ButtonStyle.secondary)
        edit_btn.callback = edit_cb; pc_btn.callback = pc_cb; view.add_item(edit_btn); view.add_item(pc_btn)
        
        if isinstance(target, discord.Interaction): await target.response.send_message(embed=embed, view=view)
        else: await target.send(embed=embed, view=view)
    else:
        if isinstance(target, discord.Interaction): await target.response.send_message(embed=embed)
        else: await target.send(embed=embed)

# --- Commandes Duels et Évolution ---

@bot.command()
async def evolve(ctx, slot: int): await cmd_evolve(ctx.author, ctx, slot)
@bot.tree.command(name="evolve", description="Lance un défi Eau/Feu/Plante pour faire évoluer un Pokémon.")
@discord.app_commands.describe(slot="Numéro du slot (1-6) du Pokémon à faire évoluer.")
async def slash_evolve(interaction: discord.Interaction, slot: int): await cmd_evolve(interaction.user, interaction, slot)

async def cmd_evolve(user, target, slot: int):
    uid = user.id; deck = user_decks.get(uid, {}).get("deck", []); 
    if not deck: return await (target.response.send_message if isinstance(target, discord.Interaction) else target.send)("Deck vide.")
    if slot < 1 or slot > len(deck): return await (target.response.send_message if isinstance(target, discord.Interaction) else target.send)("Slot invalide.")
    card = deck[slot-1]; last = card.get("last_evolution", 0)
    
    if time.time() - last < EVOLUTION_COOLDOWN:
        rem = EVOLUTION_COOLDOWN - (time.time() - last); h = int(rem//3600); m = int((rem%3600)//60)
        return await (target.response.send_message if isinstance(target, discord.Interaction) else target.send)(f"Cooldown actif. Reviens dans {h}h{m}m.")
    
    if user_decks.get(uid, {}).get("pokedollars", 0) < ECONOMY["EVOLVE_COST"]:
        return await (target.response.send_message if isinstance(target, discord.Interaction) else target.send)(f"❌ Évolution coûte **₽{ECONOMY['EVOLVE_COST']}**. Solde insuffisant. (`/solde`)")
    
    if uid in rps_challenges: return await (target.response.send_message if isinstance(target, discord.Interaction) else target.send)("Défi Eau-Feu-Plante déjà en cours.")
    
    add_pokedollars(uid, -ECONOMY["EVOLVE_COST"])
    rps_challenges[uid] = {"slot":slot, "wins":0, "losses":0, "target_wins":3, "max_rounds":5}
    msg = f"Défi Évolution pour **{card['name_fr']}** (Slot {slot}). Coût : **₽{ECONOMY['EVOLVE_COST']}**. Gagne 3/5 avec `/pfc [eau/feu/plante]`."
    if isinstance(target, discord.Interaction): await target.response.send_message(msg)
    else: await target.send(msg)

@bot.command()
async def pfc(ctx, choice: str): await cmd_pfc(ctx.author, ctx, choice)
@bot.tree.command(name="pfc", description="Joue au défi Eau/Feu/Plante pour l'évolution.")
@discord.app_commands.choices(choice=[
    discord.app_commands.Choice(name="Eau", value="eau"),
    discord.app_commands.Choice(name="Feu", value="feu"),
    discord.app_commands.Choice(name="Plante", value="plante"),
])
@discord.app_commands.describe(choice="Votre choix : Eau, Feu ou Plante.")
async def slash_pfc(interaction: discord.Interaction, choice: discord.app_commands.Choice): await cmd_pfc(interaction.user, interaction, choice.value)

async def cmd_pfc(user, target, choice: str):
    uid = user.id; choices_map = {"eau": "💧", "feu": "🔥", "plante": "🌿"}
    if uid not in rps_challenges: 
        msg = "Aucun défi. Lance `/evolve [slot]` d'abord."
        if isinstance(target, discord.Interaction): await target.response.send_message(msg, ephemeral=True)
        else: await target.send(msg)
        return

    bot_choice = random.choice(list(choices_map.keys())); win_map = {"eau":"feu", "feu":"plante", "plante":"eau"}
    ch = rps_challenges[uid]; res = f"**{choices_map[choice]} {choice.capitalize()}** vs **{choices_map[bot_choice]} {bot_choice.capitalize()}**. "
    
    if choice == bot_choice: res += "Égalité."
    elif win_map[choice] == bot_choice: ch["wins"] += 1; res += "Victoire !"
    else: ch["losses"] += 1; res += "Défaite..."
    
    rounds = ch["wins"] + ch["losses"]
    if ch["wins"] >= ch["target_wins"]:
        slot = ch["slot"]; card = user_decks[uid]["deck"][slot-1]
        await (target.response.send_message if isinstance(target, discord.Interaction) else target.send)(res)
        await process_evolution_success(target, uid, slot, card); del rps_challenges[uid]
    elif rounds >= ch["max_rounds"]:
        await (target.response.send_message if isinstance(target, discord.Interaction) else target.send)(f"{res} Défi échoué.")
        del rps_challenges[uid]
    else:
        msg = f"{res} Score: {ch['wins']}/{ch['target_wins']} (Manches: {rounds}/{ch['max_rounds']})"
        if isinstance(target, discord.Interaction): await target.response.send_message(msg)
        else: await target.send(msg)

async def process_evolution_success(target, user_id, slot_number, current_card):
    next_id = None; url = current_card.get("evolution_chain_url")
    if url: next_id = await fetch_next_evolution_id_from_chain(url, current_card.get("id"))
    if not next_id: return await (target.response.send_message if isinstance(target, discord.Interaction) else target.send)("Aucune évolution disponible.")
    
    new_card = await fetch_pokemon_details(next_id, is_shiny=current_card.get("is_shiny", False))
    if not new_card: return
    
    deck = user_decks.get(user_id, {}).get("deck", []); idx = slot_number - 1
    new_card["evolution_stage"] = current_card.get("evolution_stage",0) + 1; new_card["evolution_limit"] = current_card.get("evolution_limit",2); new_card["last_evolution"] = time.time()
    deck[idx] = new_card
    
    collection = user_decks.get(user_id, {}).get("collection", [])
    for i, c in enumerate(collection):
        if (c.get("id") == current_card.get("id") and c.get("name_fr") == current_card.get("name_fr") and c.get("is_shiny", False) == current_card.get("is_shiny", False)):
            collection[i] = new_card; break
            
    reward = ECONOMY["EVOLVE_REWARD"]; add_pokedollars(user_id, reward)
    update_best_card(user_id); save_user_decks()
    
    rarity_info = get_card_rarity_info(new_card)
    embed = discord.Embed(title="✨ ÉVOLUTION RÉUSSIE ✨", description=f"{current_card['name_fr']} ➡️ **{new_card['name_fr']}** !\n\n**+ ₽{reward} Pokédollars !**", color=rarity_info.get("color"))
    embed.set_author(name=target.user.display_name if isinstance(target, discord.Interaction) else target.author.display_name, icon_url=target.user.display_avatar.url if isinstance(target, discord.Interaction) else target.author.display_avatar.url)
    if new_card.get("image_url"): embed.set_image(url=new_card["image_url"])
    embed.add_field(name="BST", value=f"{current_card['bst']} ➡️ **{new_card['bst']}**", inline=True)
    embed.add_field(name="Rareté", value=f"{rarity_info.get('emoji')} {rarity_info.get('rarity_level')}", inline=True)
    if isinstance(target, discord.Interaction): await target.followup.send(embed=embed)
    else: await target.send(embed=embed)


@bot.command()
async def deckduel(ctx, opponent: discord.Member): await cmd_deckduel(ctx, opponent)
@bot.tree.command(name="deckduel", description="Défie un utilisateur dans un duel stratégique (3 cartes, Énergie).")
@discord.app_commands.describe(opponent="L'utilisateur à défier.")
async def slash_deckduel(interaction: discord.Interaction, opponent: discord.Member): await cmd_deckduel(interaction, opponent)

async def cmd_deckduel(target, opponent):
    ctx = target if isinstance(target, commands.Context) else target.client.get_channel(target.channel_id)
    user = target.author if isinstance(target, commands.Context) else target.user
    
    if opponent.bot or opponent.id == user.id: 
        msg = "Impossible de défier un bot ou vous-même."
        if isinstance(target, discord.Interaction): await target.response.send_message(msg, ephemeral=True)
        else: await target.send(msg)
        return
        
    uid = user.id; oid = opponent.id
    deck_u = user_decks.get(uid, {}).get("deck", []); deck_o = user_decks.get(oid, {}).get("deck", [])
    if len(deck_u) < 3: 
        msg = f"{user.display_name}, tu dois avoir 3 cartes minimum dans ton deck actif (`/deck`)."
        if isinstance(target, discord.Interaction): await target.response.send_message(msg, ephemeral=True)
        else: await target.send(msg)
        return
    if len(deck_o) < 3: 
        msg = f"{opponent.display_name} doit avoir 3 cartes minimum dans son deck actif."
        if isinstance(target, discord.Interaction): await target.response.send_message(msg, ephemeral=True)
        else: await target.send(msg)
        return
    
    if isinstance(target, discord.Interaction): await target.response.defer()
    
    view = CardSelectionView(uid, deck_u, num_cards_required=3, timeout=90.0)
    msg_select = f"<@{uid}>, sélectionne 3 cartes pour le duel :"
    if isinstance(target, discord.Interaction): msg_obj = await target.followup.send(msg_select, view=view)
    else: msg_obj = await target.send(msg_select, view=view)
    
    await view.wait()
    if not view.confirmed: await msg_obj.edit(content="Sélection annulée."); return
    challenger_cards = [deck_u[i] for i in view.selected]
    
    card_list = "\n".join([f"{i+1}. {c['name_fr']} {get_rarity_emoji(c.get('rarity_level','Commun'))}" for i,c in enumerate(challenger_cards)])
    embed = discord.Embed(title="⚔️ Défi DeckDuel", description=f"{opponent.mention}, {user.display_name} te défie !\nCartes sélectionnées:\n{card_list}", color=discord.Color.red())
    
    accept = Button(label="✅ Accepter", style=discord.ButtonStyle.success); decline = Button(label="❌ Refuser", style=discord.ButtonStyle.danger)
    
    async def acb(interaction: discord.Interaction):
        if interaction.user.id != oid: await interaction.response.send_message("Pas pour vous.", ephemeral=True); return
        await interaction.response.edit_message(content=f"{opponent.display_name} accepte. Sélectionne tes 3 cartes :", embed=None, view=None)
        
        view2 = CardSelectionView(oid, deck_o, num_cards_required=3, timeout=90.0)
        msg_select_o = await interaction.channel.send(f"<@{oid}>, sélectionne 3 cartes :", view=view2)
        await view2.wait()
        if not view2.confirmed: await msg_select_o.edit(content="Sélection annulée par l'adversaire."); return
        defender_cards = [deck_o[i] for i in view2.selected]
        
        manager = DeckDuelManager(ctx, uid, oid, challenger_cards, defender_cards)
        await interaction.channel.send(f"DeckDuel: <@{uid}> vs <@{oid}> ! Que le meilleur gagne !")
        await manager.send_battle_update()
        
    async def dcb(interaction: discord.Interaction):
        if interaction.user.id != oid: await interaction.response.send_message("Pas pour vous.", ephemeral=True); return
        await interaction.response.edit_message(content=f"{opponent.display_name} a refusé.", embed=None, view=None)
        
    accept.callback = acb; decline.callback = dcb
    v = View(timeout=120.0); v.add_item(accept); v.add_item(decline)
    await msg_obj.edit(content=f"{opponent.mention}, {user.display_name} vous défie.", embed=embed, view=v)
    
# --- Commandes Mini-jeux ---

@bot.command()
async def devine(ctx): await cmd_devine(ctx)
@bot.tree.command(name="devine", description="Quel est ce Pokémon ? Défloutage progressif.")
async def slash_devine(interaction: discord.Interaction): await cmd_devine(interaction)

async def cmd_devine(target):
    global current_guess_game
    if not all_pokemon_list: return await (target.response.send_message if isinstance(target, discord.Interaction) else target.send)("Données non chargées.")
    if current_guess_game and current_guess_game.get("channel_id") == (target.channel_id if isinstance(target, discord.Interaction) else target.channel.id): 
        msg = "Un jeu est déjà en cours dans ce salon. `/jcp` pour abandonner."
        if isinstance(target, discord.Interaction): await target.response.send_message(msg, ephemeral=True)
        else: await target.send(msg)
        return
        
    if isinstance(target, discord.Interaction): await target.response.defer()
        
    pick = random.choice(all_pokemon_list); card = await fetch_pokemon_details(pick["id"], is_shiny=False)
    if not card: return
    
    file = await get_blurred_sprite_file(card["id"], is_shiny=False, blur_level=25)
    if not file: return
    
    random_move = random.choice(card.get("moves", [{"name": "Charge"}]))["name"]
    
    current_guess_game = {"id": card["id"], "name": card["name_en"].lower(), "name_fr": card["name_fr"].lower(), "channel_id": (target.channel_id if isinstance(target, discord.Interaction) else target.channel.id), "hints": 0, "generation": card.get("generation", 1), "types": card.get("types", "Inconnu"), "random_move": random_move, "image_url": card.get("image_url")}
    
    embed = discord.Embed(title="🔍 Quel est ce Pokémon ?", description="Devinez le nom (FR ou EN) en tapant dans le chat.\nUtilisez `/indice` (max 5) pour déflouter/obtenir un indice, ou `/jcp` pour abandonner.", color=discord.Color.blue())
    embed.set_author(name=target.user.display_name if isinstance(target, discord.Interaction) else target.author.display_name, icon_url=target.user.display_avatar.url if isinstance(target, discord.Interaction) else target.author.display_avatar.url)
    embed.set_image(url="attachment://pokemon_inconnu.png")
    
    if isinstance(target, discord.Interaction): await target.followup.send(embed=embed, file=file)
    else: await target.send(embed=embed, file=file)

@bot.command()
async def indice(ctx): await cmd_indice(ctx)
@bot.tree.command(name="indice", description="Donne un indice pour le jeu Devine Pokémon.")
async def slash_indice(interaction: discord.Interaction): await cmd_indice(interaction)

async def cmd_indice(target):
    global current_guess_game
    channel_id = target.channel_id if isinstance(target, discord.Interaction) else target.channel.id
    if not current_guess_game or current_guess_game.get("channel_id") != channel_id: 
        msg = "Aucun jeu en cours ici."
        if isinstance(target, discord.Interaction): await target.response.send_message(msg, ephemeral=True)
        else: await target.send(msg)
        return
    if current_guess_game["hints"] >= MAX_HINTS: 
        msg = "Plus d'indices disponibles."
        if isinstance(target, discord.Interaction): await target.response.send_message(msg, ephemeral=True)
        else: await target.send(msg)
        return
    
    if isinstance(target, discord.Interaction): await target.response.defer()
    
    current_guess_game["hints"] += 1; hint_num = current_guess_game["hints"]; pokemon_id = current_guess_game["id"]
    blur_levels = {1: 20, 2: 15, 3: 10, 4: 5, 5: 0}
    blur = blur_levels.get(hint_num, 0); file = await get_blurred_sprite_file(pokemon_id, is_shiny=False, blur_level=blur)
    
    hints_text = {1: f"**Génération :** Ce Pokémon est de la **Génération {current_guess_game.get('generation', '?')}**.", 2: f"**Type(s) :** Ce Pokémon est de type **{current_guess_game.get('types', '?')}**.", 3: f"**Attaque :** Ce Pokémon peut apprendre **{current_guess_game.get('random_move', '?')}**.", 4: "**Image défloutée !** L'image est plus nette.", 5: "**Image claire !** Dernière chance !"}
    msg = hints_text.get(hint_num, "")
    
    embed = discord.Embed(title=f"💡 Indice #{hint_num}/{MAX_HINTS}", description=msg, color=discord.Color.orange())
    embed.set_author(name=target.user.display_name if isinstance(target, discord.Interaction) else target.author.display_name, icon_url=target.user.display_avatar.url if isinstance(target, discord.Interaction) else target.author.display_avatar.url)
    
    if file: embed.set_image(url="attachment://pokemon_inconnu.png")
    
    if isinstance(target, discord.Interaction): await target.followup.send(embed=embed, file=file)
    else: await target.send(embed=embed, file=file)

@bot.command()
async def tuprefere(ctx): await cmd_tuprefere(ctx)
@bot.tree.command(name="tuprefere", description="Choisis entre deux Pokémon (gagne la carte choisie).")
async def slash_tuprefere(interaction: discord.Interaction): await cmd_tuprefere(interaction)

async def cmd_tuprefere(target):
    channel_id = target.channel_id if isinstance(target, discord.Interaction) else target.channel.id
    if channel_id in tu_prefere_games: 
        msg = "Un jeu est déjà en cours dans ce salon."
        if isinstance(target, discord.Interaction): await target.response.send_message(msg, ephemeral=True)
        else: await target.send(msg)
        return
    if len(all_pokemon_list) < 2: return
    
    if isinstance(target, discord.Interaction): await target.response.defer()
    
    pids = random.sample(all_pokemon_list, 2)
    card1 = await fetch_pokemon_details(pids[0]["id"], is_shiny=False); card2 = await fetch_pokemon_details(pids[1]["id"], is_shiny=False)
    if not card1 or not card2: return
    
    view = TuPrefereView(target, card1, card2)
    tu_prefere_games[channel_id] = view
    
    msg = f"**{target.user.mention if isinstance(target, discord.Interaction) else target.author.mention}**, choisis entre **{card1['name_fr']}** et **{card2['name_fr']}**."
    
    if isinstance(target, discord.Interaction): await target.followup.send(msg, embed=view.create_embed(), view=view)
    else: await target.send(msg, embed=view.create_embed(), view=view)


@bot.event
async def on_message(message):
    if message.author.bot: return
    global current_guess_game
    
    if current_guess_game and message.channel.id == current_guess_game.get("channel_id"):
        guess = message.content.strip().lower()
        
        if guess in ("!jcp", "/jcp", "jcp", "je sais pas"):
            embed = discord.Embed(title="💔 Abandon", description=f"La réponse était : **{current_guess_game.get('name_fr') or current_guess_game.get('name')}**", color=discord.Color.red())
            if current_guess_game.get("image_url"): embed.set_image(url=current_guess_game["image_url"])
            await message.channel.send(embed=embed); current_guess_game = None; return
        
        if guess == current_guess_game.get("name") or guess == current_guess_game.get("name_fr"):
            embed = discord.Embed(title="🎉 Bravo !", description=f"{message.author.mention} a trouvé : **{current_guess_game.get('name_fr')}** !", color=discord.Color.green())
            if current_guess_game.get("image_url"): embed.set_image(url=current_guess_game["image_url"])
            
            reward = ECONOMY["GUESS_REWARD"]; add_pokedollars(message.author.id, reward)
            embed.add_field(name="Récompense", value=f"**+ ₽{reward} Pokédollars !**", inline=False)
            
            await message.channel.send(embed=embed); current_guess_game = None; return

    await bot.process_commands(message)


# ----------------- RUN -----------------
if __name__ == "__main__":
    if not TOKEN:
        print("❌ Erreur : DISCORD_BOT_TOKEN introuvable dans .env")
        raise SystemExit("Token manquant")
        
    bot.run(TOKEN)