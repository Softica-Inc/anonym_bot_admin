# admin_bot/bot.py
import asyncio
from aiogram import Bot, Dispatcher, Router
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram import F

from config import settings
from handlers import (
    cmd_start, cmd_new_bot, handle_token, handle_mode, cmd_cancel,
    NewBotStates, cmd_create_chat, handle_chat_title,
    cmd_invite, cmd_auth, handle_password,
    AuthStates, inline_router, ChatStates, cmd_members, handle_members_menu,
    MemberStates, handle_invite_team_generate, on_invite_team_count, TeamInviteStates, on_invite_team_input,
    on_extend_input, handle_choose_bot, handle_admin_push, handle_push_room, handle_push_text, AdminPushStates,
    handle_linkgroup_groupid, LinkGroupStates, handle_edit_member, handle_add_member, handle_remove_member,
    handle_member_action, handle_change_password
)


async def main():
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
    dp = Dispatcher(storage=MemoryStorage())

    # Register handlers
    dp.message.register(handle_change_password, AuthStates.waiting_new_password)
    dp.message.register(cmd_start, Command(commands=['start']))
    dp.message.register(cmd_new_bot, Command(commands=['new_bot']))
    dp.message.register(cmd_cancel, Command(commands=['cancel']))
    dp.message.register(handle_token, NewBotStates.waiting_token)
    dp.message.register(handle_mode, NewBotStates.waiting_mode)
    dp.message.register(cmd_create_chat, Command(commands=['create_chat']))
    dp.message.register(cmd_invite, Command(commands=['invite']))
    # dp.message.register(handle_invite_details, NewBotStates.waiting_invite_details)
    dp.message.register(cmd_auth, Command(commands=['auth']))
    dp.message.register(handle_password, AuthStates.waiting_password)
    dp.message.register(cmd_members, Command(commands=['members']))
    dp.message.register(handle_add_member, MemberStates.waiting_add)
    dp.message.register(handle_remove_member, MemberStates.waiting_remove)
    dp.message.register(handle_edit_member, MemberStates.waiting_edit)  # 👈 новий
    dp.callback_query.register(handle_member_action, F.data.startswith("members_remove_"))
    dp.callback_query.register(handle_member_action, F.data.startswith("members_edit_"))
    dp.callback_query.register(inline_router)

    dp.callback_query.register(handle_invite_team_generate, F.data == "invite_team_generate")
    dp.message.register(on_invite_team_count, TeamInviteStates.waiting_count)
    dp.message.register(on_invite_team_input, TeamInviteStates.waiting_pseudonyms)
    dp.message.register(on_extend_input, TeamInviteStates.waiting_extend)
    dp.message.register(handle_chat_title, ChatStates.waiting_title)
    dp.message.register(cmd_create_chat, Command(commands=['create_chat']))
    dp.callback_query.register(handle_choose_bot, F.data.startswith("choose_bot_"))
    dp.callback_query.register(handle_admin_push, F.data == "admin_push")
    dp.callback_query.register(handle_push_room, F.data.startswith("push_room_"))
    dp.message.register(handle_push_text, AdminPushStates.waiting_text)
    dp.message.register(handle_linkgroup_groupid, LinkGroupStates.waiting_group_id)

    # Усі callback-и обробляються тут
    dp.callback_query.register(inline_router)

    # Set commands
    await bot.set_my_commands([
        BotCommand(command='start', description='Start admin bot'),
        BotCommand(command='new_bot', description='Register new bot token'),
        BotCommand(command='create_chat', description='Create a new chat room'),
        BotCommand(command='invite', description='Generate invite link'),
        BotCommand(command='cancel', description='Cancel operation'),
        BotCommand(command='auth', description='Authenticate as admin'),
    ])

    print('Starting admin bot (polling) ...')
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == '__main__':
    asyncio.run(main())
