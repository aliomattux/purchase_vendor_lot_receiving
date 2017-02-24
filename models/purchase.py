from openerp.osv import osv, fields
from openerp.tools.translate import _
from datetime import datetime
from pprint import pprint as pp


class PurchaseOrder(osv.osv):
    _inherit = 'purchase.order'

    def get_lines_to_receive(self, cr, uid, purchase_id, product_id):
        query = "SELECT SUM(line.product_qty) AS qty, lot.location AS lot_location," \
		" COALESCE(line.location, null) AS location" \
		"\nFROM stock_vendor_lot lot" \
		"\nJOIN stock_vendor_lot_line line ON (lot.id = line.vendor_lot)" \
		"\nWHERE lot.purchase = %s AND product = %s" \
		"\nAND lot.state = 'putaway'" \
		"\nGROUP BY line.location, lot.location" % (purchase_id, product_id)
	cr.execute(query)

        return cr.dictfetchall()


    def _prepare_order_line_move(self, cr, uid, order, order_line, picking_id, group_id, context=None):
        ''' prepare the stock move data from the PO line. This function returns a list of dictionary ready to be used in stock.move's create()'''
        product_uom = self.pool.get('product.uom')
        price_unit = order_line.price_unit
        if order_line.taxes_id:
            taxes = self.pool['account.tax'].compute_all(cr, uid, order_line.taxes_id, price_unit, 1.0,
                                                             order_line.product_id, order.partner_id)
            price_unit = taxes['total']
        if order_line.product_uom.id != order_line.product_id.uom_id.id:
            price_unit *= order_line.product_uom.factor / order_line.product_id.uom_id.factor
        if order.currency_id.id != order.company_id.currency_id.id:
            #we don't round the price_unit, as we may want to store the standard price with more digits than allowed by the currency
            price_unit = self.pool.get('res.currency').compute(cr, uid, order.currency_id.id, order.company_id.currency_id.id, price_unit, round=False, context=context)
        res = []

        if order.location_id.usage == 'customer':
            name = order_line.product_id.with_context(dict(context or {}, lang=order.dest_address_id.lang)).display_name
        else:
            name = order_line.name or ''

        move_template = {
            'name': name,
            'product_id': order_line.product_id.id,
            'product_uom': order_line.product_uom.id,
            'product_uos': order_line.product_uom.id,
            'date': order.date_order,
            'date_expected': fields.date.date_to_datetime(self, cr, uid, order_line.date_planned, context),
            'location_id': order.partner_id.property_stock_supplier.id,
            'picking_id': picking_id,
            'partner_id': order.dest_address_id.id,
            'move_dest_id': False,
            'state': 'draft',
            'purchase_line_id': order_line.id,
            'company_id': order.company_id.id,
            'price_unit': price_unit,
            'picking_type_id': order.picking_type_id.id,
            'group_id': group_id,
            'procurement_id': False,
            'origin': order.name,
            'route_ids': order.picking_type_id.warehouse_id and [(6, 0, [x.id for x in order.picking_type_id.warehouse_id.route_ids])] or [],
            'warehouse_id':order.picking_type_id.warehouse_id.id,
            'invoice_state': order.invoice_method == 'picking' and '2binvoiced' or 'none',
        }

	receive_lines = self.get_lines_to_receive(cr, uid, order.id, order_line.product_id.id)
	received_qty = float(order_line.qty_received)

	for line in receive_lines:
	    print line
	    new_move = move_template.copy()
	    new_qty = float(line['qty'])
	    new_move['product_uom_qty'] = new_qty
	    new_move['product_uos_qty'] = new_qty
            new_move['location_dest_id'] = line.get('location') or \
		line.get('lot_location') or order.location_id.id
	    received_qty += new_qty
            res.append(new_move)

	order_line.qty_received = received_qty
        return res


    def _create_stock_moves(self, cr, uid, order, order_lines, picking_id=False, context=None):
        """Creates appropriate stock moves for given order lines, whose can optionally create a
        picking if none is given or no suitable is found, then confirms the moves, makes them
        available, and confirms the pickings.
        If ``picking_id`` is provided, the stock moves will be added to it, otherwise a standard
        incoming picking will be created to wrap the stock moves (default behavior of the stock.move)
        Modules that wish to customize the procurements or partition the stock moves over
        multiple stock pickings may override this method and call ``super()`` with
        different subsets of ``order_lines`` and/or preset ``picking_id`` values.
        :param browse_record order: purchase order to which the order lines belong
        :param list(browse_record) order_lines: purchase order line records for which picking
                                                and moves should be created.
        :param int picking_id: optional ID of a stock picking to which the created stock moves
                               will be added. A new picking will be created if omitted.
        :return: None
        """
        stock_move = self.pool.get('stock.move')
        todo_moves = []
        new_group = self.pool.get("procurement.group").create(cr, uid, {'name': order.name, 'partner_id': order.partner_id.id}, context=context)

        for order_line in order_lines:
	    if order_line.qty_pending_receipt < 1:
		continue
            if order_line.state == 'cancel':
                continue
            if not order_line.product_id:
                continue

            if order_line.product_id.type in ('product', 'consu'):
                for vals in self._prepare_order_line_move(cr, uid, order, order_line, \
			picking_id, new_group, context=context):
		    print 'VALS', vals
                    move = stock_move.create(cr, uid, vals, context=context)
                    todo_moves.append(move)

        todo_moves = stock_move.action_confirm(cr, uid, todo_moves)
        stock_move.force_assign(cr, uid, todo_moves)


    _columns = {
	'lp_state': fields.selection([
				('cancel', 'Canceled'),
				('draft', 'Draft'),
				('confirm', 'Pending Receipt'),
				('pending_partial', 'Partially Received'),
				('exception', 'Exception'),
				('received', 'Received'),
				('billed', 'Billed'),
	], 'State', copy=False),
#	'license_plates': fields.one2many('stock.vendor.lot', 'purchases', string="License Plates"),
    }

    _defaults = {
	'lp_state': 'draft'
    }

#	def except_reconciliation_items(self, cr, uid, product_ids)
#	    cr.execute("SELECT line.id" \
#	    "\nFROM stock_vendor_lot_line line" \
#	    "\nJOIN stock_vendor_lot lot ON (line.vendor_lot = lot.id)" \
#	    "\nWHERE lot.state IN ('verification')"
#	    "\nAND product = IN %s",(tuple(product_ids),))
#	    results = cr.fetchall()
#	    line_ids = [z[0] for z in results]
#
#	    cr.execute("UPDATE stock_vendor_lot_line line" \
#		"SET exception = True"
#		"WHERE line.id IN %s",(tuple(line_ids),))


    def button_confirm_po(self, cr, uid, ids, context=None):
	return self.write(cr, uid, ids[0], {'lp_state': 'confirm'})


    def reconcile_purchase_order(self, cr, uid, ids, context=None):
	query = "UPDATE stock_vendor_lot" \
		"\nSET state = 'putaway'" \
		"\nWHERE purchase = %s" % ids[0]
	cr.execute(query)

	purchase = self.browse(cr, uid, ids[0])
	purchase.lp_state = 'reconciled'
	return True


	#Get only items not yet received
	query = "SELECT id FROM purchase_order_line" \
		"\nWHERE order_id = %s" \
		"\nAND state != 'cancel'" \
		"AND SUM(product_qty - qty_received) > 0" % ids[0]

	cr.execute(query)
	res = cr.fetchall()
	line_ids = [z[0] for z in res]
	print line_ids

        cr.execute("""SELECT line.product_id, SUM((line.product_qty - line.qty_received) - item.product_qty) AS remaining_qty FROM purchase_order_line line \
                JOIN stock_vendor_lot lot ON (line.order_id = lot.purchase AND lot.state = 'verification') \
                LEFT OUTER JOIN stock_vendor_lot_line item ON (line.product_id = item.product AND lot.id = item.vendor_lot) WHERE line.id IN %s \
                GROUP BY line.product_id""",(tuple(line_ids),))

	lines = cr.dictfetchall()
	pp(lines)
#	for line in lines:
#	    if line['qty'] > 0:
#		exception_products.append(line['product_id'])
#	if exception_products:
#	    self.except_reconciliation_items(self, cr, exception_products)
#
#	return True




    def button_receive_purchase_order(self, cr, uid, ids, context=None):
	picking_obj = self.pool.get('stock.picking')
        for order in self.browse(cr, uid, ids):
            picking_vals = {
                'picking_type_id': order.picking_type_id.id,
                'partner_id': order.partner_id.id,
                'date': order.date_order,
                'origin': order.name
            }
            picking_id = picking_obj.create(cr, uid, picking_vals, context=context)
            self._create_stock_moves(cr, uid, order, order.order_line, picking_id, context=context)

	    #Complete the picking
	    picking = picking_obj.browse(cr, uid, picking_id)
	    picking.date_done = datetime.utcnow()
	    picking.do_transfer()
            query = "UPDATE stock_vendor_lot" \
                "\nSET state = 'done'" \
                "\nWHERE purchase = %s" % order.id
            cr.execute(query)
	    order.lp_state = 'received'
        return True


    def button_view_license_plates(self, cr, uid, ids, context=None):
        if context is None:
            context = {}
        mod_obj = self.pool.get('ir.model.data')
        dummy, action_id = tuple(mod_obj.get_object_reference(cr, uid, 'stock_vendor_lot_receiving', 'view_vendor_lot_tree'))
        action = self.pool.get('ir.actions.act_window').read(cr, uid, action_id, context=context)

        pick_ids = []
        for po in self.browse(cr, uid, ids, context=context):
            pick_ids += [picking.id for picking in po.license_plates]

        #override the context to get rid of the default filtering on picking type
        action['context'] = {}
        #choose the view_mode accordingly
 #       if len(pick_ids) > 1 or len(pick_ids) == 0:
#	    pass
#            action['domain'] = "[('id','in',[" + ','.join(map(str, pick_ids)) + "])]"
 #       else:
  #          res = mod_obj.get_object_reference(cr, uid, 'stock_vendor_lot_receiving', 'view_vendor_lot_form')
   #         action['views'] = [(res and res[1] or False, 'form')]
    #        action['res_id'] = pick_ids and pick_ids[0] or False
        return action


class PurchaseOrderLine(osv.osv):
    _inherit = 'purchase.order.line'

    def _remaining_receipt_count(self, cr, uid, ids, field_name, arg, context=None):
        if not ids:
            return {}
	cr.execute("""SELECT line.id, SUM(line.product_qty - line.qty_received) FROM purchase_order_line line \
		GROUP BY line.id""",(tuple(ids),))

        res = dict(cr.fetchall())
        return res



    _columns = {
	'qty_received': fields.float('Received'),
	'qty_remaining_receipt': fields.function(_remaining_receipt_count, method=True, type="float", string="Remaining Qty"),
    }
