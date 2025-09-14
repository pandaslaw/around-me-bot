import asyncio
from logging import getLogger
import json

import requests
from telegram import Update, BotCommand, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    CallbackContext,
    ApplicationBuilder,
    ContextTypes,
    Application,
)

from src.config.config import app_settings
from src.config.logging_config import setup_logging
from src.places_api import get_nearby_places
from src.utils import generate_answer, escape_markdown_v2

logger = getLogger(__name__)

# Store user context for callback handling
user_contexts = {}


async def send_welcome(update: Update, context: CallbackContext):
    logger.info("Starting a conversation...")
    greeting_text = (
        "🏛️ *Welcome to the History Around Me Bot!* 🌍\n\n"
        "I'm your AI-powered travel guide! Send your location to discover "
        "fascinating historical and cultural landmarks nearby.\n\n"
        "📍 Click the button below to share your current location."
    )

    button = KeyboardButton("📍 Send Location", request_location=True)
    reply_markup = ReplyKeyboardMarkup([[button]], one_time_keyboard=True, resize_keyboard=True)

    await update.message.reply_text(
        greeting_text, 
        reply_markup=reply_markup, 
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def health_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id in app_settings.ADMIN_USER_IDS:
        await context.bot.send_message(chat_id=user_id, text="Bot is live and running!")
        logger.info(f"User {user_id} checked bot's status via /health command. Bot is live and running!")
    else:
        logger.warning(f"Unauthorized /health command from user {user_id}")


async def location(update: Update, context: CallbackContext) -> None:
    """Handle location messages from users."""
    logger.info("=== LOCATION HANDLER TRIGGERED ===")
    
    if not update.message or not update.message.location:
        logger.error("No location data in message")
        await update.message.reply_text("❌ No location data received. Please try again.")
        return
        
    user_location = update.message.location
    lat = user_location.latitude
    lon = user_location.longitude
    user_id = update.message.from_user.id

    logger.info(f"Received location from user {user_id}: {lat}, {lon}")

    # Show typing indicator while processing
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # Get location name using reverse geocoding with fallbacks
    location_name = _get_location_name_with_fallbacks(lat, lon)

    # Determine user language preference from Telegram
    user_lang = _detect_user_language(update)
    logger.info(f"Detected user language: {user_lang}")

    # Show typing indicator while getting places
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # Get nearby places within 10km radius
    logger.info("Searching for nearby places...")
    places = get_nearby_places(lat, lon, radius=10000, lang=user_lang)
    logger.info(f"Found {len(places)} places")
    
    if not places:
        logger.info("No places found, sending fallback message")
        await send_reply_text(
            update, 
            "🔍 Unfortunately, I couldn't find any notable landmarks or cultural sites nearby\\. "
            "Try moving to a different location or check back later\\!"
        )
        return

    # Store context for callback handling
    user_contexts[user_id] = {
        "location": location_name,
        "coordinates": (lat, lon),
        "places": places,
        "language": user_lang
    }
    logger.info(f"Stored context for user {user_id} with language {user_lang}")

    # Show typing indicator while generating AI overview
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # Generate brief overview
    logger.info("Generating places overview...")
    places_overview = await generate_places_overview(places, location_name, user_lang)
    
    # Create inline buttons for each place
    keyboard = []
    for i, place in enumerate(places[:5]):  # Limit to 5 places
        button_text = f"🏛️ {place['name'][:30]}..." if len(place['name']) > 30 else f"🏛️ {place['name']}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"details_{i}")])
    
    # Add "More nearby places" button if there are more places
    if len(places) > 5:
        keyboard.append([InlineKeyboardButton("🔍 More nearby places", callback_data="more_places")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Add disclaimer
    disclaimer = (
        "\n\n⚠️ *Disclaimer:* This information is AI\\-generated and may not be completely accurate\\. "
        "Please verify important details from official sources\\."
    )
    
    full_message = places_overview + disclaimer
    
    logger.info("Sending response to user...")
    await update.message.reply_text(
        full_message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN_V2
    )
    logger.info("=== LOCATION HANDLER COMPLETED ===")


def _detect_user_language(update: Update) -> str:
    """
    Detect user's preferred language from Telegram interface or user data.
    Returns 'en' for English or 'ru' for Russian.
    """
    try:
        # Try to get language from user's Telegram language code
        if update.message and update.message.from_user:
            user = update.message.from_user
            
            # Check user's language code
            if hasattr(user, 'language_code') and user.language_code:
                lang_code = user.language_code.lower()
                logger.info(f"User Telegram language code: {lang_code}")
                
                # Map language codes to supported languages
                if lang_code.startswith('ru'):
                    return 'ru'
                elif lang_code.startswith('en'):
                    return 'en'
                # Add more language mappings as needed
                
            # Check user's first name for Cyrillic characters (Russian indicator)
            if user.first_name:
                # Simple heuristic: if name contains Cyrillic characters, likely Russian speaker
                cyrillic_pattern = r'[а-яё]'
                import re
                if re.search(cyrillic_pattern, user.first_name.lower()):
                    logger.info("Detected Cyrillic in user name, using Russian")
                    return 'ru'
                    
    except Exception as e:
        logger.warning(f"Error detecting user language: {e}")
    
    # Default to English
    logger.info("Using default language: English")
    return 'en'


async def generate_places_overview(places, location_name, lang="en"):
    """Generate AI-powered overview of nearby places."""
    if not places:
        return f"📍 *{location_name}*\n\nNo notable landmarks found nearby\\."
    
    # Create a structured list of places for the AI prompt
    places_list = []
    for i, place in enumerate(places[:5]):
        place_info = f"**{place['name']}**"
        
        # Add type information
        place_type = place.get('tourism') or place.get('historic') or place.get('amenity')
        if place_type:
            place_info += f" ({place_type})"
        
        # Add distance
        place_info += f" - {int(place['distance'])}m away"
        
        # Add any available description or Wikipedia extract
        if place.get('wikipedia_extract'):
            place_info += f"\n{place['wikipedia_extract'][:150]}..."
        elif place.get('description'):
            place_info += f"\n{place['description']}"
        
        places_list.append(place_info)

    places_text = "\n\n".join(places_list)
    
    prompt = f"""You are a knowledgeable local guide. The user is currently in {location_name} and can see these landmarks around them:

{places_text}

Create a response that includes:
1. A brief welcome mentioning the city/area they're in
2. A clear list of the nearby landmarks they can visually see, each with 2-3 engaging sentences describing what makes it interesting

Requirements:
- Write in {'Russian' if lang == 'ru' else 'English'}
- Be enthusiastic and welcoming
- Focus on what makes each place historically/culturally significant
- Keep descriptions concise but engaging (2-3 sentences per place)
- Use this format:

🏛️ **Place Name** (distance)
Brief engaging description about what makes this place special and interesting to visit.

Example format:
🏛️ **Pirosmani Monument** (150m)
This bronze bust commemorates Niko Pirosmani, Georgia's most beloved naive painter who captured rural life in the early 20th century. The monument stands as a tribute to the artist who painted with such passion that he often traded his works for food and wine.

Start with: "You're in [location]! Here are the fascinating landmarks you can see around you:" """

    try:
        logger.info("Generating AI overview for places...")
        overview = generate_answer(prompt)
        
        # Clean up the response and ensure proper formatting
        formatted_overview = escape_markdown_v2(overview)
        
        return f"📍 *{escape_markdown_v2(location_name)}*\n\n{formatted_overview}\n\n*Tap any landmark below for more details:*"
    except Exception as e:
        logger.error(f"Failed to generate overview: {e}")
        # Fallback: create a simple list
        fallback_text = f"📍 *{escape_markdown_v2(location_name)}*\n\n"
        fallback_text += "Here are the interesting places you can see around you:\n\n"
        
        for place in places[:3]:
            fallback_text += f"🏛️ **{escape_markdown_v2(place['name'])}** \\({int(place['distance'])}m away\\)\n"
            place_type = place.get('tourism') or place.get('historic') or place.get('amenity')
            if place_type:
                fallback_text += f"A {escape_markdown_v2(place_type)} worth exploring\\.\n\n"
        
        fallback_text += "*Tap any landmark below for detailed information:*"
        return fallback_text


async def handle_callback_query(update: Update, context: CallbackContext):
    """Handle inline button callbacks."""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    await query.answer()  # Acknowledge the callback

    if user_id not in user_contexts:
        await query.edit_message_text("❌ Session expired. Please send your location again.")
        return

    user_context = user_contexts[user_id]
    places = user_context["places"]
    lang = user_context["language"]

    if data.startswith("details_"):
        # Show typing indicator while generating detailed info
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        # Show detailed information about a specific place
        place_index = int(data.split("_")[1])
        if place_index < len(places):
            place = places[place_index]
            user_context["current_place"] = place["name"]  # Store current place for topic generation
            detailed_info = await generate_detailed_place_info(place, lang)
            
            # Create dynamic follow-up buttons
            keyboard = await generate_dynamic_buttons(place, lang)
            keyboard.append([InlineKeyboardButton("⬅️ Back to overview", callback_data="back_overview")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            disclaimer = (
                "\n\n⚠️ *Disclaimer:* This information is AI\\-generated\\. "
                "Please verify important details from official sources\\."
            )
            
            await query.edit_message_text(
                detailed_info + disclaimer,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN_V2
            )

    elif data.startswith("topic_"):
        # Show typing indicator while generating topic info
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        # Handle dynamic topic exploration
        topic = data.split("_", 1)[1]
        place_name = user_context.get("current_place", "this location")
        
        topic_info = await generate_topic_info(topic, place_name, lang)
        
        keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_details")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        disclaimer = (
            "\n\n⚠️ *Disclaimer:* This information is AI\\-generated\\. "
            "Please verify important details from official sources\\."
        )
        
        await query.edit_message_text(
            topic_info + disclaimer,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN_V2
        )

    elif data == "back_overview":
        # Go back to places overview
        await location_from_context(update, context, user_context)

    elif data == "back_details":
        # Go back to detailed place info
        place_name = user_context.get("current_place")
        if place_name:
            # Find the place in the places list
            for i, place in enumerate(places):
                if place["name"] == place_name:
                    # Show typing indicator
                    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
                    
                    detailed_info = await generate_detailed_place_info(place, lang)
                    keyboard = await generate_dynamic_buttons(place, lang)
                    keyboard.append([InlineKeyboardButton("⬅️ Back to overview", callback_data="back_overview")])
                    
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    disclaimer = (
                        "\n\n⚠️ *Disclaimer:* This information is AI\\-generated\\. "
                        "Please verify important details from official sources\\."
                    )
                    
                    await query.edit_message_text(
                        detailed_info + disclaimer,
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                    break

    elif data == "more_places":
        # Show additional places
        additional_places = places[5:10] if len(places) > 5 else []
        if additional_places:
            keyboard = []
            for i, place in enumerate(additional_places):
                button_text = f"🏛️ {place['name'][:30]}..." if len(place['name']) > 30 else f"🏛️ {place['name']}"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"details_{i+5}")])
            
            keyboard.append([InlineKeyboardButton("⬅️ Back to main places", callback_data="back_overview")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "🔍 *More places nearby:*",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN_V2
            )


async def generate_detailed_place_info(place, lang="en"):
    """Generate detailed AI-powered information about a specific place."""
    place_data = {
        "name": place["name"],
        "type": place.get("tourism") or place.get("historic") or place.get("amenity", "landmark"),
        "distance": int(place["distance"]),
        "wikipedia": place.get("wikipedia_extract", ""),
        "description": place.get("description", ""),
        "website": place.get("website", "")
    }

    prompt = f"""You are an expert local guide. Provide detailed, fascinating information about this landmark:

Name: {place_data['name']}
Type: {place_data['type']}
Distance: {place_data['distance']}m away
{f"Wikipedia info: {place_data['wikipedia']}" if place_data['wikipedia'] else ""}
{f"Description: {place_data['description']}" if place_data['description'] else ""}

Requirements:
- Write in {'Russian' if lang == 'ru' else 'English'}
- 3-4 sentences with interesting historical/cultural facts
- Include practical visitor information if relevant
- Be engaging and informative
- Focus on what makes this place special or unique
- Don't just repeat basic information"""

    try:
        logger.info(f"Generating detailed info for {place_data['name']}...")
        detailed_info = generate_answer(prompt)
        result = f"🏛️ **{escape_markdown_v2(place['name'])}**\n\n{escape_markdown_v2(detailed_info)}"
        
        if place.get("website"):
            result += f"\n\n🌐 [Official Website]({place['website']})"
        if place.get("wikipedia_url"):
            result += f"\n📖 [Wikipedia]({place['wikipedia_url']})"
            
        return result
    except Exception as e:
        logger.error(f"Failed to generate detailed info: {e}")
        return f"🏛️ **{escape_markdown_v2(place['name'])}**\n\nSorry, I couldn't generate detailed information right now\\. Please try again later\\."


async def generate_dynamic_buttons(place, lang="en"):
    """Generate AI-powered dynamic buttons for related topics."""
    place_info = f"Name: {place['name']}, Type: {place.get('tourism') or place.get('historic') or place.get('amenity')}"
    
    # Ensure language is properly specified in the prompt
    language_instruction = "English" if lang == "en" else "Russian" if lang == "ru" else "English"
    
    prompt = f"""Given this landmark: {place_info}

Suggest 2-3 interesting related topics that visitors might want to learn about. Topics should be:
- Specific and engaging (not generic)
- Related to history, culture, architecture, or local significance
- Suitable for curious travelers
- Written ONLY in {language_instruction} language
- NO Georgian, Arabic, or other scripts - use Latin alphabet only

Format as: topic1|topic2|topic3 (max 25 chars each, no extra text)

Examples for {language_instruction}: 
- English: "Architecture Style|Historical Events|Local Legends"
- Russian: "Архитектура|История|Легенды"

IMPORTANT: Respond ONLY in {language_instruction}. Do not use any other language or script."""

    try:
        logger.info(f"Generating dynamic buttons for {place['name']} in {language_instruction}...")
        topics_response = generate_answer(prompt)
        topics = [t.strip() for t in topics_response.split("|") if t.strip()][:3]
        
        # Validate that topics are in the correct language/script
        keyboard = []
        for topic in topics:
            if len(topic) <= 35 and _is_valid_language_script(topic, lang):
                keyboard.append([InlineKeyboardButton(f"💡 {topic}", callback_data=f"topic_{topic}")])
            else:
                logger.warning(f"Skipping invalid topic: {topic} (wrong language or too long)")
        
        # If no valid topics, add a fallback
        if not keyboard:
            fallback_topic = "Learn more" if lang == "en" else "Узнать больше"
            keyboard.append([InlineKeyboardButton(f"💡 {fallback_topic}", callback_data=f"topic_General Information")])
        
        return keyboard
    except Exception as e:
        logger.error(f"Failed to generate dynamic buttons: {e}")
        fallback_topic = "Learn more" if lang == "en" else "Узнать больше"
        return [[InlineKeyboardButton(f"💡 {fallback_topic}", callback_data="topic_General Information")]]


def _is_valid_language_script(text: str, lang: str) -> bool:
    """
    Check if text uses the expected script for the given language.
    """
    import re
    
    if lang == "ru":
        # For Russian, expect Cyrillic characters
        cyrillic_pattern = r'[а-яё]'
        return bool(re.search(cyrillic_pattern, text.lower()))
    elif lang == "en":
        # For English, expect Latin characters only (no Cyrillic, Georgian, etc.)
        latin_only_pattern = r'^[a-zA-Z0-9\s\-\.\,\!\?\'\"]*$'
        return bool(re.match(latin_only_pattern, text))
    
    # Default: allow any text
    return True


async def generate_topic_info(topic, place_name, lang="en"):
    """Generate information about a specific topic related to the place."""
    prompt = f"""You are a knowledgeable guide. Provide interesting information about "{topic}" related to {place_name}.

Requirements:
- Write in {'Russian' if lang == 'ru' else 'English'}
- 2-3 sentences with specific, engaging details
- Focus on the requested topic
- Be informative but concise
- Include interesting facts or stories if relevant"""

    try:
        logger.info(f"Generating topic info for '{topic}' related to {place_name}...")
        topic_info = generate_answer(prompt)
        return f"💡 **{escape_markdown_v2(topic)}**\n\n{escape_markdown_v2(topic_info)}"
    except Exception as e:
        logger.error(f"Failed to generate topic info: {e}")
        return f"💡 **{escape_markdown_v2(topic)}**\n\nSorry, I couldn't generate information about this topic right now\\."


async def location_from_context(update: Update, context: CallbackContext, user_context):
    """Recreate location overview from stored context."""
    places = user_context["places"]
    location_name = user_context["location"]
    lang = user_context["language"]
    
    places_overview = await generate_places_overview(places, location_name, lang)
    
    keyboard = []
    for i, place in enumerate(places[:5]):
        button_text = f"🏛️ {place['name'][:30]}..." if len(place['name']) > 30 else f"🏛️ {place['name']}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"details_{i}")])
    
    if len(places) > 5:
        keyboard.append([InlineKeyboardButton("🔍 More nearby places", callback_data="more_places")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    disclaimer = (
        "\n\n⚠️ *Disclaimer:* This information is AI\\-generated and may not be completely accurate\\. "
        "Please verify important details from official sources\\."
    )
    
    await update.callback_query.edit_message_text(
        places_overview + disclaimer,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def handle_text_message(update: Update, context: CallbackContext):
    logger.info("Processing user's text message")
    user_input = update.message.text

    # Show typing indicator while generating response
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # Generate AI response with disclaimer
    logger.info("Generating AI response for text message...")
    llm_response = generate_answer(user_input)
    
    disclaimer = (
        "\n\n⚠️ *Disclaimer:* This response is AI\\-generated\\. "
        "Please verify important information from reliable sources\\."
    )
    
    full_response = llm_response + disclaimer
    await send_reply_text(update, full_response)


async def send_reply_text(update: Update, text: str):
    # escaped_text = escape_markdown_v2(text)
    escaped_text = text
    await update.message.reply_text(escaped_text, parse_mode=ParseMode.MARKDOWN_V2)


def _get_location_name_with_fallbacks(lat: float, lon: float) -> str:
    """
    Get location name using multiple reverse geocoding APIs with fallbacks.
    """
    logger.info("Getting location name via reverse geocoding...")
    
    # API 1: BigDataCloud (free, no key required)
    try:
        response = requests.get(
            f"https://api.bigdatacloud.net/data/reverse-geocode-client?latitude={lat}&longitude={lon}&localityLanguage=en",
            timeout=8
        )
        response.raise_for_status()
        location_data = response.json()
        if location_data.get('locality') and location_data.get('countryName'):
            location_name = f"{location_data['locality']}, {location_data['countryName']}"
            logger.info(f"Location name from BigDataCloud: {location_name}")
            return location_name
    except Exception as e:
        logger.warning(f"BigDataCloud API failed: {e}")
    
    # API 2: Nominatim (free, no key required)
    try:
        response = requests.get(
            f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&addressdetails=1",
            timeout=8,
            headers={'User-Agent': 'HistoryAroundMeBot/1.0'}
        )
        response.raise_for_status()
        location_data = response.json()
        
        address = location_data.get('address', {})
        city = address.get('city') or address.get('town') or address.get('village') or address.get('municipality')
        country = address.get('country')
        
        if city and country:
            location_name = f"{city}, {country}"
            logger.info(f"Location name from Nominatim: {location_name}")
            return location_name
    except Exception as e:
        logger.warning(f"Nominatim API failed: {e}")
    
    # API 3: LocationIQ (free tier available)
    if hasattr(app_settings, 'LOCATIONIQ_API_KEY') and app_settings.LOCATIONIQ_API_KEY:
        try:
            response = requests.get(
                f"https://us1.locationiq.com/v1/reverse.php?key={app_settings.LOCATIONIQ_API_KEY}&lat={lat}&lon={lon}&format=json",
                timeout=8
            )
            response.raise_for_status()
            location_data = response.json()
            
            address = location_data.get('address', {})
            city = address.get('city') or address.get('town') or address.get('village')
            country = address.get('country')
            
            if city and country:
                location_name = f"{city}, {country}"
                logger.info(f"Location name from LocationIQ: {location_name}")
                return location_name
        except Exception as e:
            logger.warning(f"LocationIQ API failed: {e}")
    
    # Fallback: Use coordinates
    location_name = f"Coordinates: {lat:.4f}, {lon:.4f}"
    logger.info(f"Using fallback location name: {location_name}")
    return location_name


async def register_handlers(app: Application):
    """Register all command and message handlers."""
    logger.info("Registering handlers...")
    
    app.add_handler(CommandHandler("start", send_welcome))
    app.add_handler(CommandHandler("health", health_check))
    
    # Location handler - must be registered before text handler
    location_handler = MessageHandler(filters.LOCATION, location)
    app.add_handler(location_handler)
    logger.info("Location handler registered")
    
    # Re-enable callback handler for inline buttons
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    logger.info("Callback query handler registered")
    
    # Text handler - should be last to avoid conflicts
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
    )
    logger.info("Text message handler registered")
    
    commands = [
        BotCommand("start", "Start interacting with the bot"),
    ]
    await app.bot.set_my_commands(commands)
    logger.info("Bot commands set successfully")


async def main():
    """Main entry point for the bot."""
    bot_app = ApplicationBuilder().token(app_settings.TELEGRAM_BOT_TOKEN).build()

    # Initialize the application
    await bot_app.initialize()

    # Register all handlers
    await register_handlers(bot_app)

    try:
        logger.info("Starting the bot...")
        await bot_app.start()
        await bot_app.updater.start_polling()
        await asyncio.Future()
    except (KeyboardInterrupt, SystemExit):
        logger.error("Bot stopped.")
    finally:
        logger.info("Shutting down the bot...")


if __name__ == "__main__":
    setup_logging()
    asyncio.run(main())
