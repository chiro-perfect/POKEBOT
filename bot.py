# bot.py - PokéDeck version complète avec système de dés, boutons de vol colorés et images
import discord
from discord.ext import commands
from discord.ui import Button, View
import asyncio
import aiohttp
import random
import io
import json
import os
import time
from PIL import Image, ImageFilter
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
print("TOKEN chargé ?", bool(TOKEN))

POKEAPI_BASE_URL = "https://pokeapi.co/api/v2"
DATA_FILE = "user_decks.json"

RARITIES = {
    "Mythique": {"chance": 0.01, "min_bst": 680, "color": 0xFFFFFF, "rank": 5, "emoji": "⚪"},
    "Légendaire": {"chance": 0.04, "min_bst": 600, "color": 0x9B59B6, "rank": 4, "emoji": "🟣"},
    "Épique": {"chance": 0.10, "min_bst": 500, "color": 0xE74C3C, "rank": 3, "emoji": "🔴"},
    "Rare": {"chance": 0.35, "min_bst": 400, "color": 0xF1C40F, "rank": 2, "emoji": "🟡"},
    "Commun": {"chance": 0.50, "min_bst": 0, "color": 0x8B4513, "rank": 1, "emoji": "🟤"},
    "Chrome": {"chance": 0.001, "min_bst": 0, "color": 0xFFD700, "rank": 6, "emoji": "🌟"},
}

BIGDECK_COOLDOWN = 24 * 60 * 60
EVOLUTION_COOLDOWN = 24 * 60 * 60
BIGDECK_REROLLS = 5
MAX_HINTS = 5

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

user_decks = {}
all_pokemon_list = []
bigdeck_sessions = {}
rps_challenges = {}
duel_challenges = {}
active_deck_duels = {}
current_guess_game = None

# ---------------- Persistence ----------------
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
                    v.setdefault("last_bigdeck", 0)
                    v.setdefault("best_card", None)
                    for c in v["deck"]:
                        c.setdefault("last_draw", 0)
                        c.setdefault("is_shiny", False)
                        c.setdefault("moves", [])
                    user_decks[uid] = v
                else:
                    user_decks[uid] = {"deck": list(v), "last_bigdeck": 0, "best_card": None}
            print(f"✅ {len(user_decks)} decks chargés.")
        except Exception as e:
            print("❌ Erreur chargement:", e)
            user_decks = {}
    else:
        user_decks = {}

def save_user_decks():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in user_decks.items()}, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print("❌ Erreur sauvegarde:", e)

def update_best_card(user_id):
    ud = user_decks.setdefault(user_id, {"deck": [], "last_bigdeck": 0, "best_card": None})
    deck = ud["deck"]
    if not deck:
        ud["best_card"] = None
        return
    best = None
    for c in deck:
        if not best:
            best = c
            continue
        r1 = RARITIES.get(c.get("rarity_level","Commun"), {}).get("rank", 0)
        r2 = RARITIES.get(best.get("rarity_level","Commun"), {}).get("rank", 0)
        if r1 > r2 or (r1 == r2 and c.get("bst",0) > best.get("bst",0)) or (r1==r2 and c.get("bst",0)==best.get("bst",0) and c.get("is_shiny",False) and not best.get("is_shiny",False)):
            best = c
    ud["best_card"] = best.copy() if best else None

def add_card_to_deck(user_id, card):
    ud = user_decks.setdefault(user_id, {"deck": [], "last_bigdeck": 0, "best_card": None})
    deck = ud["deck"]
    card = dict(card)
    card.setdefault("last_draw", time.time())
    if len(deck) >= 6:
        oldest = min(deck, key=lambda x: x.get("last_draw", 0))
        deck.remove(oldest)
        removed = oldest
    else:
        removed = None
    deck.append(card)
    update_best_card(user_id)
    save_user_decks()
    return removed

# ---------------- PokeAPI helpers ----------------
def calculate_bst(stats):
    return sum(s.get("base_stat", 0) for s in stats)

async def fetch_pokemon_moves(pokemon_id):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{POKEAPI_BASE_URL}/pokemon/{pokemon_id}") as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
            moves = []
            candidates = data.get("moves", [])[:20]
            for m in random.sample(candidates, min(len(candidates), 8)):
                name_en = m["move"]["name"].replace("-", " ").capitalize()
             
                try:
                    async with aiohttp.ClientSession() as s2:
                        async with s2.get(m["move"]["url"]) as r:
                            if r.status == 200:
                                move_data = await r.json()
                                name_fr = next((n["name"] for n in move_data.get("names",[]) if n["language"]["name"]=="fr"), name_en)
                            else:
                                name_fr = name_en
                except:
                    name_fr = name_en
                    
                power = random.choice([30, 40, 50, 60, 70, 80, 90, 100])
                moves.append({"name": name_fr, "power": power})
            if not moves:
                moves = [{"name":"Charge","power":50}]
            return moves[:4]
    except Exception:
        return [{"name":"Charge","power":50}]

async def fetch_pokemon_details(pokemon_id, is_shiny=False):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{POKEAPI_BASE_URL}/pokemon/{pokemon_id}") as r1:
                if r1.status != 200:
                    return None
                pdata = await r1.json()
            async with aiohttp.ClientSession() as session2:
                async with session2.get(f"{POKEAPI_BASE_URL}/pokemon-species/{pokemon_id}") as r2:
                    sdata = await r2.json() if r2.status == 200 else {}
            
            bst = calculate_bst(pdata.get("stats", []))
            rarity_level = "Commun"
            for name, info in sorted(RARITIES.items(), key=lambda x: -x[1]["min_bst"]):
                if name != "Chrome" and bst >= info.get("min_bst", 0):
                    rarity_level = name
                    break
            
            image_url = pdata["sprites"].get("front_shiny") if is_shiny else pdata["sprites"].get("front_default")
            name_fr = next((n["name"] for n in sdata.get("names", []) if n["language"]["name"] == "fr"), pdata.get("name","").capitalize()).capitalize()
            types = ", ".join([t["type"]["name"].capitalize() for t in pdata.get("types", [])])
            moves = await fetch_pokemon_moves(pokemon_id)
            stats_text = "\n".join([f"- {s['stat']['name'].capitalize()}: {s['base_stat']}" for s in pdata.get("stats", [])])
            
            # Génération
            generation = 1
            if sdata.get("generation"):
                gen_name = sdata["generation"]["name"]
                try:
                    generation = int(gen_name.split("-")[-1].replace("i","1").replace("v","5").replace("x","10"))
                except:
                    generation = 1
            
            return {
                "id": pdata.get("id"),
                "name_en": pdata.get("name","").capitalize(),
                "name_fr": name_fr,
                "bst": bst,
                "rarity_level": "Chrome" if is_shiny else rarity_level,
                "image_url": image_url,
                "is_shiny": is_shiny,
                "types": types,
                "stats": stats_text,
                "moves": moves,
                "evolution_chain_url": sdata.get("evolution_chain", {}).get("url"),
                "evolution_stage": 0,
                "evolution_limit": 2,
                "last_evolution": 0,
                "last_draw": 0,
                "generation": generation,
            }
    except Exception as e:
        return None

async def load_all_pokemon():
    global all_pokemon_list
    if all_pokemon_list:
        return
    print("⏳ Chargement des Pokémon...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{POKEAPI_BASE_URL}/pokemon?limit=1000") as resp:
                if resp.status != 200:
                    return
                data = await resp.json()
            tasks = []
            for item in data.get("results", []):
                tasks.append(session.get(item["url"]))
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            for r in responses:
                try:
                    if isinstance(r, Exception) or r.status != 200:
                        continue
                    detail = await r.json()
                    bst = calculate_bst(detail.get("stats", []))
                    all_pokemon_list.append({"id": detail["id"], "name": detail["name"], "bst": bst})
                except Exception:
                    continue
        print(f"✅ {len(all_pokemon_list)} Pokémon chargés.")
    except Exception as e:
        print("❌ Erreur:", e)

def get_rarity_by_bst(bst):
    for name, info in sorted(RARITIES.items(), key=lambda x: -x[1]["min_bst"]):
        if name != "Chrome" and bst >= info.get("min_bst", 0):
            return name
    return "Commun"

def get_random_pokemon_id_by_rarity(target_rarity):
    candidates = [p["id"] for p in all_pokemon_list if get_rarity_by_bst(p.get("bst",0)) == target_rarity]
    return random.choice(candidates) if candidates else None

def get_rarity_emoji(name):
    return RARITIES.get(name, {}).get("emoji", "❓")

def get_rarity_color(name):
    return RARITIES.get(name, {}).get("color", discord.Color.blue().value)

def get_button_style_for_rarity(rarity_name):
    """Retourne le style de bouton selon la rareté"""
    styles = {
        "Mythique": discord.ButtonStyle.secondary,
        "Légendaire": discord.ButtonStyle.primary,
        "Épique": discord.ButtonStyle.danger,
        "Rare": discord.ButtonStyle.success,
        "Commun": discord.ButtonStyle.secondary,
        "Chrome": discord.ButtonStyle.success
    }
    return styles.get(rarity_name, discord.ButtonStyle.secondary)

async def get_blurred_sprite_file(pokemon_id, is_shiny=False, blur_level=18):
    try:
        if is_shiny:
            url = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/shiny/{pokemon_id}.png"
        else:
            url = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{pokemon_id}.png"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        blurred = img.filter(ImageFilter.GaussianBlur(blur_level))
        buf = io.BytesIO()
        blurred.save(buf, format="PNG")
        buf.seek(0)
        return discord.File(fp=buf, filename="pokemon_inconnu.png")
    except Exception:
        return None

# ----------------- VUES (UI) -----------------
class CardSelectionView(View):
    def __init__(self, user_id, deck, num_cards_required=3, timeout=90.0):
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.deck = deck[:6]
        self.num_cards_required = num_cards_required
        self.selected = []
        self.confirmed = False

        for i, card in enumerate(self.deck):
            label = f"#{i+1} {card.get('name_fr','?')[:18]}"
            emoji = get_rarity_emoji(card.get("rarity_level","Commun"))
            btn = Button(label=f"{emoji} {label}", style=discord.ButtonStyle.secondary, custom_id=f"cs_{i}")
            btn.callback = self.make_cb(i)
            self.add_item(btn)
        confirm_btn = Button(label=f"✅ Confirmer (0/{self.num_cards_required})", style=discord.ButtonStyle.success, custom_id="cs_confirm", disabled=True)
        confirm_btn.callback = self.confirm_cb
        self.add_item(confirm_btn)

    def make_cb(self, idx):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Ce n'est pas votre sélection.", ephemeral=True)
                return
            if idx in self.selected:
                self.selected.remove(idx)
            else:
                if len(self.selected) >= self.num_cards_required:
                    await interaction.response.send_message(f"Max {self.num_cards_required} cartes.", ephemeral=True)
                    return
                self.selected.append(idx)
            for item in self.children:
                if isinstance(item, Button) and item.custom_id.startswith("cs_") and item.custom_id != "cs_confirm":
                    i = int(item.custom_id.split("_")[1])
                    if i in self.selected:
                        item.style = discord.ButtonStyle.primary
                        if not item.label.startswith("✓ "):
                            item.label = "✓ " + item.label
                    else:
                        item.style = discord.ButtonStyle.secondary
                        item.label = item.label.replace("✓ ", "")
            confirm_btn = next((x for x in self.children if getattr(x, "custom_id", "") == "cs_confirm"), None)
            if confirm_btn:
                confirm_btn.disabled = len(self.selected) != self.num_cards_required
                confirm_btn.label = f"✅ Confirmer ({len(self.selected)}/{self.num_cards_required})"
            try:
                await interaction.response.edit_message(view=self)
            except:
                pass
        return cb

    async def confirm_cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Pas votre sélection.", ephemeral=True)
            return
        self.confirmed = True
        for item in self.children:
            item.disabled = True
        try:
            await interaction.response.edit_message(content=f"✅ Sélection OK ({self.num_cards_required} cartes).", view=self)
        except:
            pass
        self.stop()

class AttackSelectView(View):
    def __init__(self, manager, user_id, timeout=60.0):
        super().__init__(timeout=timeout)
        self.manager = manager
        self.user_id = user_id
        active_card = manager.get_active_card(user_id)
        if not active_card: return
        self.moves = active_card.get("moves", [])[:4] or [{"name":"Charge","power":50}]
        for i, m in enumerate(self.moves):
            btn = Button(label=f"{m['name']} ({m['power']})", style=discord.ButtonStyle.primary, custom_id=f"atk_{user_id}_{i}")
            btn.callback = self.make_cb(i)
            self.add_item(btn)
        auto_btn = Button(label="🎲 Lancer le dé (auto)", style=discord.ButtonStyle.secondary, custom_id=f"atk_auto_{user_id}")
        auto_btn.callback = self.auto_cb
        self.add_item(auto_btn)

    def make_cb(self, idx):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Pas votre tour.", ephemeral=True)
                return
            for item in self.children:
                item.disabled = True
            try:
                await interaction.response.edit_message(view=self)
            except:
                pass
            await self.manager.handle_move(self.user_id, idx)
            self.stop()
        return cb

    async def auto_cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Pas votre tour.", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        try:
            await interaction.response.edit_message(view=self)
        except:
            pass
        dice = random.randint(1, 6)
        moves = self.moves
        chosen_idx = pick_move_index_from_dice(dice, moves)
        await self.manager.handle_move(self.user_id, chosen_idx, forced_dice=dice, auto_selected=True)
        self.stop()

    async def on_timeout(self):
        await self.manager.handle_timeout(self.user_id)

class StealSelectView(View):
    """Vue avec boutons colorés selon la rareté pour le vol de carte"""
    def __init__(self, ctx, info):
        super().__init__(timeout=60.0)
        self.ctx = ctx
        self.info = info
        loser_cards = info.get("loser_cards_ko", [])
        for i, c in enumerate(loser_cards):
            emoji = get_rarity_emoji(c.get("rarity_level","Commun"))
            label = f"{c.get('name_fr','?')[:20]}"
            # Couleur du bouton selon la rareté
            btn_style = get_button_style_for_rarity(c.get("rarity_level", "Commun"))
            btn = Button(label=f"{emoji} {label}", style=btn_style, custom_id=f"steal_{i}")
            btn.callback = self.make_cb(i)
            self.add_item(btn)

    def make_cb(self, idx):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.info.get("winner_id"):
                await interaction.response.send_message("Seul le gagnant peut voler.", ephemeral=True)
                return
            stolen = self.info["loser_cards_ko"][idx]
            loser_deck = user_decks.get(self.info["loser_id"], {}).get("deck", [])
            for c in list(loser_deck):
                if c.get("id") == stolen.get("id") and c.get("is_shiny", False) == stolen.get("is_shiny", False):
                    loser_deck.remove(c)
                    break
            add_card_to_deck(self.info["winner_id"], stolen)
            update_best_card(self.info["loser_id"])
            save_user_decks()
            
            emoji = get_rarity_emoji(stolen.get("rarity_level", "Commun"))
            await interaction.response.edit_message(
                content=f"✅ {interaction.user.mention} a volé **{stolen['name_fr']}** {emoji} ({stolen.get('rarity_level','')}) !", 
                embed=None,
                view=None
            )
            try:
                del active_deck_duels[self.ctx.channel.id]
            except KeyError:
                pass
        return cb

    async def on_timeout(self):
        try:
            await self.ctx.send("⏳ Temps écoulé pour le vol.")
        except:
            pass

def pick_move_index_from_dice(dice_value: int, moves: list) -> int:
    if not moves:
        return 0
    m = len(moves)
    ordering = sorted(range(len(moves)), key=lambda i: moves[i]['power'])
    bucket = 6.0 / m
    bucket_idx = int((dice_value - 1) // bucket)
    if bucket_idx < 0: bucket_idx = 0
    if bucket_idx >= m: bucket_idx = m - 1
    return ordering[bucket_idx]

# ---------------- Deck Duel Manager ----------------
class DeckDuelManager:
    def __init__(self, ctx, challenger_id, opponent_id, challenger_cards, opponent_cards):
        self.ctx = ctx
        self.channel = ctx.channel
        self.guild = ctx.guild
        self.challenger_id = challenger_id
        self.opponent_id = opponent_id
        self.challenger_cards = [dict(c) for c in challenger_cards]
        self.opponent_cards = [dict(c) for c in opponent_cards]
        for c in self.challenger_cards + self.opponent_cards:
            if "stats_dict" not in c:
                d = {}
                for line in c.get("stats","").splitlines():
                    if ":" in line:
                        k, v = line.split(":",1)
                        try:
                            d[k.strip().lower()] = int("".join([ch for ch in v if ch.isdigit()]))
                        except:
                            pass
                c["stats_dict"] = d
                c["stats_dict"].setdefault("hp", c.get("bst", 50))
                c.setdefault("current_hp", c["stats_dict"]["hp"])
            else:
                c.setdefault("current_hp", c["stats_dict"].get("hp", c.get("bst",50)))
        self.challenger_index = 0
        self.opponent_index = 0
        sc = self.challenger_cards[0].get("stats_dict", {}).get("speed", 0)
        so = self.opponent_cards[0].get("stats_dict", {}).get("speed", 0)
        self.active_player_id = self.challenger_id if sc >= so else self.opponent_id
        self.turn = 1
        self.last_message = None
        self.status = "FIGHT"

    def get_active_card(self, user_id):
        if user_id == self.challenger_id:
            return self.challenger_cards[self.challenger_index]
        return self.opponent_cards[self.opponent_index]

    def get_opponent_card(self, user_id):
        if user_id == self.challenger_id:
            return self.opponent_cards[self.opponent_index]
        return self.challenger_cards[self.challenger_index]

    async def handle_timeout(self, user_id):
        if self.status != "FIGHT":
            return
        loser = user_id
        winner = self.opponent_id if loser == self.challenger_id else self.challenger_id
        await self.end_duel(winner, f"⏱️ <@{loser}> n'a pas joué à temps.")

    async def handle_move(self, user_id, move_index, forced_dice: int = None, auto_selected: bool = False):
        if self.status != "FIGHT":
            return
        attacker = self.get_active_card(user_id)
        defender = self.get_opponent_card(user_id)
        moves = attacker.get("moves", []) or [{"name":"Charge","power":50}]
        if move_index < 0 or move_index >= len(moves):
            move_index = 0
        move = moves[move_index]

        dice = forced_dice if forced_dice is not None else random.randint(1, 6)

        if dice <= 2:
            mod = 0.6; dice_text = "attaque faible"
        elif dice <= 4:
            mod = 1.0; dice_text = "attaque normale"
        else:
            mod = 1.5; dice_text = "attaque puissante"

        atk = attacker.get("stats_dict", {}).get("attack", max(1, attacker.get("bst",50)//10))
        df = defender.get("stats_dict", {}).get("defense", max(1, defender.get("bst",50)//10))
        base = move.get("power", 50)

        damage = int((atk / max(1, df)) * base * mod * random.uniform(0.9,1.1) / 2)
        damage = max(1, damage)
        defender["current_hp"] = defender.get("current_hp", defender.get("stats_dict", {}).get("hp",1)) - damage

        if auto_selected:
            dice_msg = f"🎲 {dice} — auto: {move['name']} ({move['power']}) — {dice_text}."
        else:
            dice_msg = f"🎲 {dice} — {dice_text}."

        text = f"{dice_msg}\n**{self.get_player_name(user_id)}** → **{attacker['name_fr']}** utilise **{move['name']}**. **{defender['name_fr']}** subit **-{damage} PV** ({max(0,defender['current_hp'])}/{defender['stats_dict'].get('hp','?')} PV)."

        if defender["current_hp"] <= 0:
            text += f"\n💥 **{defender['name_fr']}** est KO !"
            if user_id == self.challenger_id:
                self.opponent_index += 1
            else:
                self.challenger_index += 1
            if self.challenger_index >= len(self.challenger_cards) or self.opponent_index >= len(self.opponent_cards):
                await self.end_duel(user_id, text)
                return
            new_def = self.get_opponent_card(user_id)
            text += f"\n➡️ **{new_def['name_fr']}** entre !"
            new_att = self.get_active_card(user_id)
            if new_att.get("stats_dict", {}).get("speed",0) < new_def.get("stats_dict", {}).get("speed",0):
                self.active_player_id = self.opponent_id if user_id == self.challenger_id else self.challenger_id
        else:
            self.active_player_id = self.opponent_id if user_id == self.challenger_id else self.challenger_id

        self.turn += 1
        await self.send_battle_update(text)

    def get_player_name(self, uid):
        m = self.guild.get_member(uid)
        return m.display_name if m else f"User{uid}"

    async def send_battle_update(self, action_message=None):
        c_user = self.guild.get_member(self.challenger_id)
        o_user = self.guild.get_member(self.opponent_id)
        card_c = self.challenger_cards[self.challenger_index] if self.challenger_index < len(self.challenger_cards) else {"name_fr":"(KO)","image_url":None,"rarity_level":"", "stats_dict":{"hp":0},"current_hp":0}
        card_o = self.opponent_cards[self.opponent_index] if self.opponent_index < len(self.opponent_cards) else {"name_fr":"(KO)","image_url":None,"rarity_level":"", "stats_dict":{"hp":0},"current_hp":0}

        active = self.active_player_id
        embed = discord.Embed(title=f"⚔️ DECK DUEL — {c_user.display_name} vs {o_user.display_name} (Tour {self.turn})",
                              description=action_message or f"C'est à <@{active}>.", color=discord.Color.red())
        embed.add_field(name=f"{card_c['name_fr']} ({card_c.get('rarity_level','')})", value=f"PV: {max(0,card_c.get('current_hp',0))}/{card_c.get('stats_dict',{}).get('hp','?')}", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(name=f"{card_o['name_fr']} ({card_o.get('rarity_level','')})", value=f"PV: {max(0,card_o.get('current_hp',0))}/{card_o.get('stats_dict',{}).get('hp','?')}", inline=True)
        if card_c.get("image_url"):
            embed.set_thumbnail(url=card_c.get("image_url"))
        if card_o.get("image_url"):
            embed.set_image(url=card_o.get("image_url"))

        view = AttackSelectView(self, active, timeout=60.0)

        if self.last_message:
            try: await self.last_message.delete()
            except: pass
        self.last_message = await self.channel.send(content=f"⚡ <@{active}> — choisissez attaque ou dé auto :", embed=embed, view=view)

    async def end_duel(self, winner_id, final_message):
        self.status = "ENDED"
        loser = self.opponent_id if winner_id == self.challenger_id else self.challenger_id
        if loser == self.challenger_id:
            ko_cards = self.challenger_cards[self.challenger_index:]
        else:
            ko_cards = self.opponent_cards[self.opponent_index:]

        embed = discord.Embed(title=f"👑 VICTOIRE : {self.get_player_name(winner_id)} gagne !",
                              description=f"{final_message}\n\n**Le gagnant peut voler une carte KO en cliquant sur un bouton ci-dessous.**",
                              color=discord.Color.gold())
        if self.last_message:
            try: await self.last_message.delete()
            except: pass
        
        # Vue avec boutons colorés pour le vol
        view = StealSelectView(self.ctx, {
            "manager": self,
            "winner_id": winner_id,
            "loser_id": loser,
            "loser_cards_ko": ko_cards
        })
        
        self.last_message = await self.channel.send(embed=embed, view=view)
        active_deck_duels[self.channel.id] = {
            "manager": self,
            "winner_id": winner_id,
            "loser_id": loser,
            "loser_cards_ko": ko_cards
        }

# ----------------- BigDeck View -----------------
class BigDeckView(View):
    def __init__(self, user_id, session):
        super().__init__(timeout=120.0)
        self.user_id = user_id
        self.session = session
        reroll_btn = Button(label=f"🔄 Reroll ({session['attempts']})", style=discord.ButtonStyle.secondary)
        keep_btn = Button(label="✅ Garder", style=discord.ButtonStyle.success)
        cancel_btn = Button(label="❌ Annuler", style=discord.ButtonStyle.danger)
        reroll_btn.callback = self.reroll_cb
        keep_btn.callback = self.keep_cb
        cancel_btn.callback = self.cancel_cb
        self.add_item(reroll_btn)
        self.add_item(keep_btn)
        self.add_item(cancel_btn)

    async def reroll_cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Pas votre session.", ephemeral=True); return
        if self.session["attempts"] <= 0:
            await interaction.response.send_message("Plus de rerolls.", ephemeral=True); return
        candidate = random.choice(all_pokemon_list) if all_pokemon_list else None
        if not candidate:
            await interaction.response.send_message("Données non chargées.", ephemeral=True); return
        card = await fetch_pokemon_details(candidate["id"], is_shiny=(random.random() < RARITIES["Chrome"]["chance"]))
        if not card:
            await interaction.response.send_message("Erreur tirage.", ephemeral=True); return
        self.session["current_card"] = card
        self.session["attempts"] -= 1
        file = await get_blurred_sprite_file(card["id"], is_shiny=card.get("is_shiny",False), blur_level=10)
        rarity_emoji = get_rarity_emoji(card.get("rarity_level","Commun"))
        embed = discord.Embed(title="✨ BigDeck (reroll) ✨",
                              description=f"Rareté: {rarity_emoji} {card.get('rarity_level','?')} - BST: {card.get('bst','?')}\nRerolls: {self.session['attempts']}",
                              color=get_rarity_color(card.get("rarity_level","Commun")))
        embed.set_image(url="attachment://pokemon_inconnu.png")
        try:
            await interaction.response.edit_message(embed=embed, attachments=[file], view=self)
        except:
            await interaction.response.send_message(embed=embed, file=file, view=self)

    async def keep_cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Pas votre session.", ephemeral=True); return
        final_card = self.session.get("current_card")
        if not final_card:
            await interaction.response.send_message("Aucune carte.", ephemeral=True); return
        removed = add_card_to_deck(self.user_id, final_card)
        save_user_decks()
        msg = f"🎉 **{final_card['name_fr']}** ({final_card.get('rarity_level','')}) obtenu !"
        if removed:
            msg += f"\n🗑️ {removed['name_fr']} retiré (deck plein)."
        try:
            await interaction.response.edit_message(content=msg, embed=None, view=None)
        except:
            await interaction.response.send_message(msg)
        bigdeck_sessions.pop(self.user_id, None)

    async def cancel_cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Pas votre session.", ephemeral=True); return
        try:
            await interaction.response.edit_message(content="Tirage annulé.", embed=None, view=None)
        except:
            await interaction.response.send_message("Annulé.")
        bigdeck_sessions.pop(self.user_id, None)

    async def on_timeout(self):
        bigdeck_sessions.pop(self.user_id, None)

# ---------------- Commands ----------------
@bot.event
async def on_ready():
    print("✅ Bot prêt:", bot.user)
    load_user_decks()
    bot.loop.create_task(load_all_pokemon())

@bot.command(name="help", aliases=["aide","pokehelp"])
async def pokehelp(ctx):
    embed = discord.Embed(title="🤖 PokéBot — Aide", color=discord.Color.blue())
    embed.add_field(name="Collection", value="`!carte` — Tire une carte\n`!deck` — Affiche ton deck", inline=False)
    embed.add_field(name="BigDeck & Évolution", value="`!bigdeck` — 1x/jour, 5 rerolls\n`!evolve [slot]` — Évoluer via PFC\n`!pfc [pierre/feuille/ciseaux]`", inline=False)
    embed.add_field(name="Duels", value="`!duel @user` — Duel simple BST\n`!deckduel @user` — Duel stratégique (3 cartes, dés)", inline=False)
    embed.add_field(name="Minijeux", value="`!devine` — Quel est ce Pokémon ?\n`!indice` — Défloutage progressif", inline=False)
    await ctx.send(embed=embed)

@bot.command(name="carte")
async def cmd_carte(ctx):
    if not all_pokemon_list:
        return await ctx.send("Données en cours de chargement...")
    is_shiny = random.random() < RARITIES["Chrome"]["chance"]
    pid = random.choice(all_pokemon_list)["id"]
    card = await fetch_pokemon_details(pid, is_shiny=is_shiny)
    if not card:
        return await ctx.send("Erreur tirage.")
    removed = add_card_to_deck(ctx.author.id, card)
    emoji = get_rarity_emoji(card.get("rarity_level","Commun"))
    embed = discord.Embed(title=f"🎴 {card['name_fr']} !", color=get_rarity_color(card.get("rarity_level","Commun")))
    embed.set_thumbnail(url=card.get("image_url"))
    embed.add_field(name="Rareté", value=f"{emoji} {card.get('rarity_level')}", inline=True)
    embed.add_field(name="BST", value=str(card.get("bst","?")), inline=True)
    if removed:
        await ctx.send(f"**{card['name_fr']}** tiré — {removed['name_fr']} retiré.", embed=embed)
    else:
        await ctx.send(embed=embed)

@bot.command(name="deck")
async def cmd_deck(ctx, member: discord.Member = None):
    target = member or ctx.author
    ud = user_decks.get(target.id, {"deck":[]})
    deck = ud.get("deck", [])
    if not deck:
        return await ctx.send(f"{target.display_name} n'a pas de cartes.")
    
    # Trouver la meilleure carte (plus fort BST)
    best_card = max(deck, key=lambda c: c.get("bst", 0))
    embed = discord.Embed(title=f"🎒 Deck de {target.display_name} ({len(deck)}/6)", color=get_rarity_color(best_card.get("rarity_level", "Commun")))
    
    # Photo de profil en grand
    embed.set_author(name=target.display_name, icon_url=target.display_avatar.url)
    
    # Image du Pokémon le plus fort
    if best_card.get("image_url"):
        embed.set_image(url=best_card["image_url"])
        embed.set_footer(text=f"⭐ Meilleur: {best_card['name_fr']} (BST: {best_card['bst']})")

    for i in range(6):
        if i < len(deck):
            c = deck[i]
            emoji = get_rarity_emoji(c.get("rarity_level","Commun"))
            embed.add_field(name=f"#{i+1}: {c.get('name_fr')}", value=f"{emoji} {c.get('rarity_level')} — BST: {c.get('bst')}", inline=True)
        else:
            embed.add_field(name=f"#{i+1}", value="(Vide)", inline=True)
    await ctx.send(embed=embed)

@bot.command(name="bigdeck")
async def cmd_bigdeck(ctx):
    uid = ctx.author.id
    ud = user_decks.setdefault(uid, {"deck":[], "last_bigdeck":0, "best_card":None})
    now = time.time()
    if now - ud.get("last_bigdeck",0) < BIGDECK_COOLDOWN:
        rem = BIGDECK_COOLDOWN - (now - ud["last_bigdeck"])
        h = int(rem//3600); m = int((rem%3600)//60)
        return await ctx.send(f"⏳ Recharge dans {h}h{m}m.")
    if not all_pokemon_list:
        return await ctx.send("Données en cours de chargement.")
    candidate = random.choice(all_pokemon_list)
    card = await fetch_pokemon_details(candidate["id"], is_shiny=(random.random() < RARITIES["Chrome"]["chance"]))
    if not card:
        return await ctx.send("Erreur.")
    session = {"current_card": card, "attempts": BIGDECK_REROLLS, "start": now}
    bigdeck_sessions[uid] = session
    file = await get_blurred_sprite_file(card["id"], is_shiny=card.get("is_shiny",False), blur_level=14)
    embed = discord.Embed(title="✨ BigDeck Quotidien ✨",
                          description=f"BST: {card.get('bst','?')} — {get_rarity_emoji(card.get('rarity_level','Commun'))} {card.get('rarity_level')}\nRerolls: {session['attempts']}",
                          color=get_rarity_color(card.get("rarity_level","Commun")))
    embed.set_image(url="attachment://pokemon_inconnu.png")
    view = BigDeckView(uid, session)
    user_decks[uid]["last_bigdeck"] = now
    save_user_decks()
    if file:
        await ctx.send(embed=embed, file=file, view=view)
    else:
        await ctx.send(embed=embed, view=view)

# ----------------- Evolve / PFC -----------------
async def fetch_next_evolution_id_from_chain(evo_chain_url, current_id):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(evo_chain_url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        def traverse(chain, cur_id):
            def id_from_url(url):
                return int(url.strip("/").split("/")[-1])
            nodes = [chain]
            while nodes:
                node = nodes.pop(0)
                if id_from_url(node["species"]["url"]) == cur_id:
                    if node.get("evolves_to"):
                        return id_from_url(node["evolves_to"][0]["species"]["url"])
                    return None
                for nxt in node.get("evolves_to", []):
                    nodes.append(nxt)
            return None
        return traverse(data["chain"], current_id)
    except Exception:
        return None

async def process_evolution_success(ctx, user_id, slot_number, current_card):
    next_id = None
    url = current_card.get("evolution_chain_url")
    if url:
        next_id = await fetch_next_evolution_id_from_chain(url, current_card.get("id"))
    if not next_id:
        return await ctx.send("Aucune évolution disponible.")
    new_card = await fetch_pokemon_details(next_id, is_shiny=current_card.get("is_shiny", False))
    if not new_card:
        return await ctx.send("Erreur récupération évolution.")
    deck = user_decks.get(user_id, {}).get("deck", [])
    idx = slot_number - 1
    if idx < 0 or idx >= len(deck):
        return await ctx.send("Slot invalide.")
    new_card["evolution_stage"] = current_card.get("evolution_stage",0) + 1
    new_card["evolution_limit"] = current_card.get("evolution_limit",2)
    new_card["last_evolution"] = time.time()
    deck[idx] = new_card
    update_best_card(user_id)
    save_user_decks()
    
    # Embed avec image du nouveau Pokémon et photo de profil
    embed = discord.Embed(title="✨ ÉVOLUTION RÉUSSIE ✨", 
                          description=f"{current_card['name_fr']} ➡️ **{new_card['name_fr']}** !", 
                          color=get_rarity_color(new_card.get("rarity_level", "Commun")))
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    if new_card.get("image_url"):
        embed.set_image(url=new_card["image_url"])
    embed.add_field(name="BST", value=f"{current_card['bst']} ➡️ **{new_card['bst']}**", inline=True)
    embed.add_field(name="Rareté", value=f"{get_rarity_emoji(new_card['rarity_level'])} {new_card['rarity_level']}", inline=True)
    await ctx.send(embed=embed)

@bot.command(name="evolve")
async def cmd_evolve(ctx, slot: int = None):
    uid = ctx.author.id
    if slot is None:
        return await ctx.send("Usage: `!evolve [slot]`")
    deck = user_decks.get(uid, {}).get("deck", [])
    if not deck:
        return await ctx.send("Deck vide.")
    if slot < 1 or slot > len(deck):
        return await ctx.send("Slot invalide.")
    card = deck[slot-1]
    last = card.get("last_evolution", 0)
    if time.time() - last < EVOLUTION_COOLDOWN:
        rem = EVOLUTION_COOLDOWN - (time.time() - last)
        h = int(rem//3600); m = int((rem%3600)//60)
        return await ctx.send(f"Cooldown actif. Reviens dans {h}h{m}m.")
    if uid in rps_challenges:
        return await ctx.send("Défi PFC déjà en cours.")
    rps_challenges[uid] = {"slot":slot, "wins":0, "losses":0, "target_wins":3, "max_rounds":5}
    await ctx.send(f"Défi pour **{card['name_fr']}** (Slot {slot}). Gagne 3/5 avec `!pfc [pierre/feuille/ciseaux]`")

@bot.command(name="pfc", aliases=["rps"])
async def cmd_pfc(ctx, choice: str = None):
    uid = ctx.author.id
    if uid not in rps_challenges:
        return await ctx.send("Aucun défi. Lance `!evolve [slot]` d'abord.")
    if choice is None:
        ch = rps_challenges[uid]
        return await ctx.send(f"Défi slot {ch['slot']}. Score {ch['wins']}/{ch['target_wins']}. Joue `!pfc [pierre/feuille/ciseaux]`.")
    choice = choice.lower()
    if choice not in ("pierre","feuille","ciseaux"):
        return await ctx.send("Choix invalide.")
    bot_choice = random.choice(["pierre","feuille","ciseaux"])
    win_map = {"pierre":"ciseaux","feuille":"pierre","ciseaux":"feuille"}
    ch = rps_challenges[uid]
    res = f"**{choice}** vs **{bot_choice}**. "
    if choice == bot_choice:
        res += "Égalité."
    elif win_map[choice] == bot_choice:
        ch["wins"] += 1; res += "Victoire !"
    else:
        ch["losses"] += 1; res += "Défaite..."
    rounds = ch["wins"] + ch["losses"]
    if ch["wins"] >= ch["target_wins"]:
        slot = ch["slot"]
        card = user_decks[uid]["deck"][slot-1]
        await process_evolution_success(ctx, uid, slot, card)
        del rps_challenges[uid]
    elif rounds >= ch["max_rounds"]:
        await ctx.send("Défi échoué.")
        del rps_challenges[uid]
    else:
        await ctx.send(f"{res} Score: {ch['wins']}/{ch['target_wins']} (Manches: {rounds}/{ch['max_rounds']})")

# ----------------- DeckDuel -----------------
@bot.command(name="deckduel")
async def cmd_deckduel(ctx, opponent: discord.Member = None):
    if not opponent:
        return await ctx.send("Mentionne un adversaire: `!deckduel @user`")
    if opponent.bot or opponent == ctx.author:
        return await ctx.send("Impossible.")
    uid = ctx.author.id; oid = opponent.id
    deck_u = user_decks.get(uid, {}).get("deck", [])
    deck_o = user_decks.get(oid, {}).get("deck", [])
    if len(deck_u) < 3: return await ctx.send("Tu dois avoir 3+ cartes.")
    if len(deck_o) < 3: return await ctx.send("Adversaire doit avoir 3+ cartes.")
    view = CardSelectionView(uid, deck_u, num_cards_required=3, timeout=90.0)
    await ctx.send(f"<@{uid}>, sélectionne 3 cartes :", view=view)
    await view.wait()
    if not view.confirmed:
        return await ctx.send("Sélection annulée.")
    challenger_cards = [deck_u[i] for i in view.selected]
    card_list = "\n".join([f"{i+1}. {c['name_fr']} {get_rarity_emoji(c.get('rarity_level','Commun'))}" for i,c in enumerate(challenger_cards)])
    embed = discord.Embed(title="⚔️ Défi DeckDuel", description=f"{opponent.mention}, {ctx.author.display_name} te défie !\nCartes:\n{card_list}", color=discord.Color.red())
    accept = Button(label="✅ Accepter", style=discord.ButtonStyle.success)
    decline = Button(label="❌ Refuser", style=discord.ButtonStyle.danger)
    async def acb(interaction: discord.Interaction):
        if interaction.user.id != oid:
            await interaction.response.send_message("Pas pour vous.", ephemeral=True); return
        await interaction.response.edit_message(content=f"{opponent.display_name} accepte. Sélectionne tes 3 cartes :", embed=None, view=None)
        view2 = CardSelectionView(oid, deck_o, num_cards_required=3, timeout=90.0)
        await ctx.send(f"<@{oid}>, sélectionne 3 cartes :", view=view2)
        await view2.wait()
        if not view2.confirmed:
            return await ctx.send("Sélection annulée.")
        defender_cards = [deck_o[i] for i in view2.selected]
        manager = DeckDuelManager(ctx, uid, oid, challenger_cards, defender_cards)
        await ctx.send(f"DeckDuel: <@{uid}> vs <@{oid}> !")
        await manager.send_battle_update()
    async def dcb(interaction: discord.Interaction):
        if interaction.user.id != oid:
            await interaction.response.send_message("Pas pour vous.", ephemeral=True); return
        await interaction.response.edit_message(content=f"{opponent.display_name} a refusé.", embed=None, view=None)
    accept.callback = acb; decline.callback = dcb
    v = View(timeout=120.0)
    v.add_item(accept); v.add_item(decline)
    await ctx.send(embed=embed, view=v)

@bot.command(name="duel")
async def cmd_duel(ctx, opponent: discord.Member = None):
    if not opponent:
        return await ctx.send("Mentionne un adversaire: `!duel @user`")
    if opponent.bot or opponent == ctx.author:
        return await ctx.send("Impossible.")
    a = user_decks.get(ctx.author.id, {}).get("deck", [])
    b = user_decks.get(opponent.id, {}).get("deck", [])
    if not a or not b:
        return await ctx.send("Les deux joueurs doivent avoir des cartes.")
    ca = random.choice(a); cb = random.choice(b)
    bst_a = ca.get("bst",0); bst_b = cb.get("bst",0)
    if bst_a > bst_b: winner = ctx.author.display_name
    elif bst_b > bst_a: winner = opponent.display_name
    else: winner = "Égalité"
    embed = discord.Embed(title="Duel BST", color=discord.Color.blurple())
    embed.add_field(name=ctx.author.display_name, value=f"{ca['name_fr']} (BST {bst_a})", inline=True)
    embed.add_field(name=opponent.display_name, value=f"{cb['name_fr']} (BST {bst_b})", inline=True)
    embed.add_field(name="Vainqueur", value=winner, inline=False)
    await ctx.send(embed=embed)

# ----------------- Devine (avec défloutage progressif) -----------------
@bot.command(name="devine")
async def cmd_devine(ctx):
    global current_guess_game
    if not all_pokemon_list:
        return await ctx.send("Données non chargées.")
    pick = random.choice(all_pokemon_list)
    card = await fetch_pokemon_details(pick["id"], is_shiny=False)
    if not card:
        return await ctx.send("Erreur.")
    # IMAGE TRÈS FLOUE au début
    file = await get_blurred_sprite_file(card["id"], is_shiny=False, blur_level=25)
    if not file:
        return await ctx.send("Impossible de charger l'image.")
    
    # Récupérer un nom d'attaque aléatoire
    random_move = random.choice(card.get("moves", [{"name": "Charge"}]))["name"]
    
    current_guess_game = {
        "id": card["id"], 
        "name": card["name_en"].lower(), 
        "name_fr": card["name_fr"].lower(), 
        "channel_id": ctx.channel.id, 
        "hints": 0,
        "generation": card.get("generation", 1),
        "types": card.get("types", "Inconnu"),
        "random_move": random_move,
        "image_url": card.get("image_url")
    }
    
    embed = discord.Embed(
        title="🔍 Quel est ce Pokémon ?", 
        description="Devinez le nom (FR ou EN) en tapant dans le chat.\nTapez `jcp` ou `je sais pas` pour abandonner.", 
        color=discord.Color.blue()
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    embed.set_image(url="attachment://pokemon_inconnu.png")
    await ctx.send(embed=embed, file=file)

@bot.command(name="indice")
async def cmd_indice(ctx):
    global current_guess_game
    if not current_guess_game or current_guess_game.get("channel_id") != ctx.channel.id:
        return await ctx.send("Aucun jeu en cours ici.")
    if current_guess_game["hints"] >= MAX_HINTS:
        return await ctx.send("Plus d'indices disponibles.")
    
    current_guess_game["hints"] += 1
    hint_num = current_guess_game["hints"]
    pokemon_id = current_guess_game["id"]
    
    # Système de défloutage progressif
    blur_levels = {
        1: 20,  # Indice 1: Génération
        2: 15,  # Indice 2: Types
        3: 10,  # Indice 3: Attaque
        4: 5,   # Indice 4: Défloutage moyen
        5: 0    # Indice 5: Image claire
    }
    
    blur = blur_levels.get(hint_num, 0)
    file = await get_blurred_sprite_file(pokemon_id, is_shiny=False, blur_level=blur)
    
    if hint_num == 1:
        msg = f"**Indice 1 — Génération :** Ce Pokémon est de la **Génération {current_guess_game.get('generation', '?')}**."
    elif hint_num == 2:
        msg = f"**Indice 2 — Type(s) :** Ce Pokémon est de type **{current_guess_game.get('types', '?')}**."
    elif hint_num == 3:
        msg = f"**Indice 3 — Attaque :** Ce Pokémon peut apprendre **{current_guess_game.get('random_move', '?')}**."
    elif hint_num == 4:
        msg = "**Indice 4 — Image défloutée !** L'image est plus nette."
    else:
        msg = "**Indice 5 — Image claire !** Dernière chance !"
    
    embed = discord.Embed(title=f"💡 Indice #{hint_num}/5", description=msg, color=discord.Color.orange())
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    if file:
        embed.set_image(url="attachment://pokemon_inconnu.png")
        await ctx.send(embed=embed, file=file)
    else:
        await ctx.send(embed=embed)

# ----------------- on_message pour devinettes -----------------
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    global current_guess_game
    
    # Gestion des devinettes
    if current_guess_game and message.channel.id == current_guess_game.get("channel_id"):
        guess = message.content.strip().lower()
        
        # 1. Gestion de l'abandon ("jcp" ou "je sais pas")
        if guess in ("!jcp", "jcp", "je sais pas"):
            embed = discord.Embed(
                title="💔 Abandon",
                description=f"La réponse était : **{current_guess_game.get('name_fr') or current_guess_game.get('name')}**",
                color=discord.Color.red()
            )
            embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
            await message.channel.send(embed=embed)
            current_guess_game = None
            return # Sort de la fonction
        
        # 2. Gestion de la bonne réponse
        if guess == current_guess_game.get("name") or guess == current_guess_game.get("name_fr"):
            embed = discord.Embed(
                title="🎉 Bravo !",
                description=f"{message.author.mention} a trouvé : **{current_guess_game.get('name_fr')}** !",
                color=discord.Color.green()
            )
            # Affiche l'image du Pokémon si disponible
            if current_guess_game.get("image_url"):
                embed.set_image(url=current_guess_game["image_url"])
                
            await message.channel.send(embed=embed)
            current_guess_game = None
            return # Sort de la fonction

    # Traitement par défaut des commandes (si ce n'est pas une devinette)
    await bot.process_commands(message)

# ----------------- Run -----------------
if __name__ == "__main__":
    if not TOKEN:
        print("❌ Erreur : DISCORD_BOT_TOKEN introuvable dans .env")
        raise SystemExit("Token manquant")
        
    bot.run(TOKEN)