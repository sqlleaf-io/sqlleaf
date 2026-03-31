class SqlGlotException(Exception):
    def __init__(self, message, table):
        super().__init__(message)

        self.message = message
        self.table = table

    def __str__(self):
        return "%s (Table=%s)" % (self.message, self.table)


class SqlLeafException(Exception):
    def __init__(self, message, table):
        super().__init__(message)

        self.message = message
        self.table = table

    def __str__(self):
        return "%s (Table=%s)" % (self.message, self.table)


class SqlLeafStoredProcedureException(Exception):
    def __init__(self, message, stored_procedure_name=""):
        super().__init__(message)

        self.message = message
        self.stored_procedure_name = stored_procedure_name

    def __str__(self):
        if self.stored_procedure_name:
            return "%s (Stored procedure: %s)" % (
                self.message,
                self.stored_procedure_name,
            )
        return "%s" % (self.message,)
