import asyncio, asyncpg
async def main():
    con = await asyncpg.connect("postgresql://flipper:flipper_secret@127.0.0.1:5432/flipper")
    cols = await con.fetch("""
        SELECT column_name, data_type FROM information_schema.columns
        WHERE table_name = 'houses' ORDER BY ordinal_position
    """)
    for c in cols:
        print(c['column_name'], c['data_type'])
    await con.close()
asyncio.run(main())
