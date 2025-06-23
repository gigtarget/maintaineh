@routes.route("/subuser/dashboard")
@subuser_required
def subuser_dashboard():
    sub_id = session.get('subuser_id')
    sub = SubUser.query.get_or_404(sub_id)
    machine = Machine.query.get_or_404(sub.assigned_machine_id)
    batch = QRBatch.query.get_or_404(machine.batch_id)
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())

    # ✅ Check if today's oiling and this week's lube are done
    oil_done = SubUserAction.query.filter_by(
        subuser_id=sub.id,
        machine_id=machine.id,
        action_type="oil",
        status="done"
    ).filter(db.func.date(SubUserAction.timestamp) == today).first() is not None

    lube_done = SubUserAction.query.filter_by(
        subuser_id=sub.id,
        machine_id=machine.id,
        action_type="lube",
        status="done"
    ).filter(SubUserAction.timestamp >= start_of_week).first() is not None

    # ✅ Get latest timestamps
    last_oil = SubUserAction.query.filter_by(
        subuser_id=sub.id,
        machine_id=machine.id,
        action_type="oil",
        status="done"
    ).order_by(SubUserAction.timestamp.desc()).first()

    last_lube = SubUserAction.query.filter_by(
        subuser_id=sub.id,
        machine_id=machine.id,
        action_type="lube",
        status="done"
    ).order_by(SubUserAction.timestamp.desc()).first()

    # ✅ Alerts (overdue)
    oil_alert = True
    if last_oil and (datetime.utcnow() - last_oil.timestamp).total_seconds() < 86400:
        oil_alert = False

    lube_alert = True
    if last_lube and (datetime.utcnow() - last_lube.timestamp).days < 6:
        lube_alert = False

    # ✅ Pass `now` for countdown display
    return render_template(
        "subuser_dashboard.html",
        subuser=sub,
        machine=machine,
        batch=batch,
        qr_codes=QRCode.query.filter_by(batch_id=batch.id).all(),
        tags=QRTag.query.filter_by(batch_id=batch.id).all(),
        oil_done=oil_done,
        lube_done=lube_done,
        last_oil_time=last_oil.timestamp if last_oil else None,
        last_lube_time=last_lube.timestamp if last_lube else None,
        oil_alert=oil_alert,
        lube_alert=lube_alert,
        now=datetime.utcnow()  # ✅ This is the fix
    )
