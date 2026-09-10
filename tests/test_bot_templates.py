import ast,os,sqlite3,sys
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services import bot_templates,telegram_detector

# One template = one job. Order matches the public catalog.
EXPECTED=["complete-group-manager","complete-channel-manager","complete-referral-rewards",
          "complete-commerce","complete-file-share","complete-media-ai-converter",
          "complete-ai-support"]


def test_catalog_contains_only_complete_products():
    rows=bot_templates.list_templates()
    assert [r["id"] for r in rows]==EXPECTED
    assert len(rows)==7 and all(r["language"]=="python" for r in rows)
    assert all(r["badge"]=="Complete" for r in rows)
    for row in rows:
        item=bot_templates.get_template(row["id"]);code=item["code"]
        assert row["name"] and row["description"] and row["category"]
        assert "BOT_TOKEN" in code and not telegram_detector.TOKEN_RE.search(code)
        analysis=telegram_detector.analyze_code(code,"python")
        assert analysis["telegram_detected"] and analysis["update_mode"]=="polling"
        compile(code,row["id"]+".py","exec")


def test_group_manager_is_one_real_moderation_product():
    code=bot_templates.get_template("complete-group-manager")["code"]
    for marker in ("captcha","restrict_chat_member","setwords","setlimit","warns","ban_chat_member","report","audit","automatic"):
        assert marker in code
    # Moderation scope only: nothing from other categories.
    for foreign in ("create_chat_invite_link","/audio/transcriptions","stock=stock-"):
        assert foreign not in code


def test_channel_manager_owns_every_channel_feature():
    code=bot_templates.get_template("complete-channel-manager")["code"]
    for marker in ("get_chat_member","create_chat_invite_link","schedule","delete_after",
                   "copy_message","edit_message_caption","edit_message_reply_markup",
                   "Tag remover","InlineKeyboardButton","broadcast","post_init(restore)"):
        assert marker in code
    # Channel management scope only: referral/payout and paid membership are
    # separate products and must not leak in.
    for foreign in ("referrer","subscriptions","expire_members","points=points+"):
        assert foreign not in code


def test_referral_rewards_has_no_channel_logic():
    code=bot_templates.get_template("complete-referral-rewards")["code"]
    for marker in ("referrer","points","withdraw","ORDER BY points DESC LIMIT 10","setrate","setmin","Withdrawal"):
        assert marker in code
    for foreign in ("create_chat_invite_link","setchannel","get_chat_member"):
        assert foreign not in code


def test_file_share_has_no_conversion_logic():
    code=bot_templates.get_template("complete-file-share")["code"]
    for marker in ("max_downloads","start=f_","downloads=downloads+1","/settings DAYS MAX_DOWNLOADS","expires"):
        assert marker in code
    for foreign in ("Image.open","PdfReader","api.ocr.space","/audio/transcriptions","qrcode.make","virustotal"):
        assert foreign not in code


def test_media_converter_has_no_share_or_scan_logic():
    code=bot_templates.get_template("complete-media-ai-converter")["code"]
    for marker in ("Image.open","PdfReader","api.ocr.space","/audio/transcriptions","/audio/speech","qrcode.make","/mode convert"):
        assert marker in code
    for foreign in ("virustotal","sha256","start=f_","downloads=downloads+1"):
        assert foreign not in code


def test_ai_store_commerce_are_full_products():
    ai=bot_templates.get_template("complete-ai-support")["code"]
    for marker in ("/chat/completions","memory","daily_limit","setprompt","broadcast","ban"):
        assert marker in ai
    store=bot_templates.get_template("complete-commerce")["code"]
    for marker in ("CREATE TABLE IF NOT EXISTS products","CREATE TABLE IF NOT EXISTS cart","CREATE TABLE IF NOT EXISTS orders","stock=stock-","Payment review","orders","panel"):
        assert marker in store


def test_no_template_blocks_one_tap_deploy():
    # Deploy is instant: no required env field, no shared secrets in code.
    for row in bot_templates.list_templates():
        item=bot_templates.get_template(row["id"])
        assert all(not f.get("required") for f in item["env_fields"]), row["id"]
        assert "os.getenv(" in item["code"]
        # Admin claim secret is delivered via env, never embedded.
        if row["id"] not in ("complete-group-manager",):
            keys={f["key"] for f in item["env_fields"]}
            assert "ADMIN_CLAIM_CODE" in keys, row["id"]


def test_every_static_schema_executes():
    checked=0
    for row in bot_templates.list_templates():
        tree=ast.parse(bot_templates.get_template(row["id"])["code"]);db=sqlite3.connect(":memory:")
        for node in ast.walk(tree):
            if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Attribute) or not node.args:continue
            if node.func.attr not in ("execute","executescript") or not isinstance(node.args[0],ast.Constant) or not isinstance(node.args[0].value,str):continue
            sql=node.args[0].value.strip()
            if sql.upper().startswith(("CREATE ","PRAGMA ")):
                (db.executescript(sql) if node.func.attr=="executescript" else db.execute(sql));checked+=1
        db.close()
    assert checked>=7
