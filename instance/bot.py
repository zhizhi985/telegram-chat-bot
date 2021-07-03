import asyncio
import typing as ty
import aiogram
import aioredis
from aiogram import Dispatcher, types, exceptions
from aiogram.contrib.fsm_storage.memory import MemoryStorage

from settings import InstanceSettings


class BotInstance:
    def __init__(self, token: str, super_chat_id: int, start_text: str,
                 invite_callback: ty.Optional[ty.Callable] = None,
                 left_callback: ty.Optional[ty.Callable] = None,
                 identify: ty.Optional[int] = None):
        self._token = token
        self._bot_id = self._token.split(":")[0]
        self._super_chat_id = super_chat_id
        self._start_text = start_text
        self._redis: aioredis.Redis = None
        self._dp: aiogram.Dispatcher = None
        self._identify = identify

        self._invite_callback = invite_callback
        self._left_callback = left_callback

    def stop_polling(self):
        self._dp.stop_polling()

    async def start_polling(self):
        self._redis = await aioredis.create_redis_pool(InstanceSettings.redis_path())

        bot = aiogram.Bot(self._token)
        self._dp = Dispatcher(bot, storage=MemoryStorage())

        # Здесь перечислены все типы сообщений, которые бот должен пересылать
        self._dp.register_message_handler(self._receive_message, content_types=[types.ContentType.TEXT,
                                                                                types.ContentType.CONTACT,
                                                                                types.ContentType.ANIMATION,
                                                                                types.ContentType.AUDIO,
                                                                                types.ContentType.DOCUMENT,
                                                                                types.ContentType.PHOTO,
                                                                                types.ContentType.STICKER,
                                                                                types.ContentType.VIDEO,
                                                                                types.ContentType.VOICE])
        # Callback-и на добавление бота в чат и удаление бота из чата
        self._dp.register_message_handler(self._receive_invite, content_types=[types.ContentType.NEW_CHAT_MEMBERS])
        self._dp.register_message_handler(self._receive_left, content_types=[types.ContentType.LEFT_CHAT_MEMBER])

        await self._dp.start_polling()

    def _message_unique_id(self, message_id) -> str:
        return self._bot_id + "-" + str(message_id)

    async def _receive_invite(self, message: types.Message):
        if not self._invite_callback:
            return

        for member in message.new_chat_members:
            if member.id == message.bot.id:
                await self._invite_callback(self._identify, message)

    async def _receive_left(self, message: types.Message):
        if not self._left_callback:
            return

        if message.left_chat_member.id == message.bot.id:
            await self._left_callback(self._identify, message)

    async def _receive_message(self, message: types.Message):
        """
        Получено обычное сообщение, вероятно, для пересыла в другой чат
        :param message:
        :return:
        """
        if message.text and message.text.startswith("/start"):
            # На команду start нужно ответить, не пересылая сообщение никуда
            await message.answer(self._start_text)
            return

        if message.chat.id != self._super_chat_id:
            # Это обычный чат: сообщение нужно переслать в супер-чат
            new_message = await message.forward(self._super_chat_id)
            await self._redis.set(self._message_unique_id(new_message.message_id), message.chat.id)
        else:
            # Это супер-чат
            if message.reply_to_message:
                # Ответ из супер-чата переслать тому пользователю,
                chat_id = await self._redis.get(self._message_unique_id(message.reply_to_message.message_id))
                if not chat_id:
                    chat_id = message.reply_to_message.forward_from_chat
                    if not chat_id:
                        await message.reply("Невозможно переслать сообщение: автор не найден")
                        return
                chat_id = int(chat_id)
                try:
                    await message.copy_to(chat_id)
                except exceptions.MessageError:
                    await message.reply("Невозможно переслать сообщение: возможно, автор заблокировал бота")
                    return
            else:
                await message.forward(self._super_chat_id)


if __name__ == '__main__':
    """
    Режим single-instance. В этом режиме не работает olgram. На сервере запускается только один feedback (instance)
    бот для пересылки сообщений. Все настройки этого бота задаются в переменных окружения на сервере. Бот работает 
    в режиме polling
    """
    bot = BotInstance(
        InstanceSettings.token(),
        InstanceSettings.super_chat_id(),
        InstanceSettings.start_text()
    )
    asyncio.get_event_loop().run_until_complete(bot.start_polling())
