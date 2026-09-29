class AutoUserFieldsAdminMixin:
    """
    Fills "who did this" fields (created_by, uploaded_by, recorded_by, ...)
    with the logged-in admin user instead of letting them be picked by hand,
    and shows them read-only.

    set_on_create: stamped only when the object is first added.
    set_on_save:   stamped on every save (e.g. updated_by).
    """

    set_on_create = ()
    set_on_save = ()

    def get_readonly_fields(self, request, obj=None):
        return (*super().get_readonly_fields(request, obj), *self.set_on_create, *self.set_on_save)

    def save_model(self, request, obj, form, change):
        if not change:
            for field in self.set_on_create:
                setattr(obj, field, request.user)
        for field in self.set_on_save:
            setattr(obj, field, request.user)
        super().save_model(request, obj, form, change)
