from kalamar.storage.alchemy import AlchemyAccessPoint


class PostgresAlchemyAccessPoint(AlchemyAccessPoint):
    protocol = "alchemy-postgresql"

    def __init__(self,config):
        super(PostgresAlchemyAccessPoint,self).__init__(config)


